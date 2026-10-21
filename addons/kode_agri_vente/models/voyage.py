from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import ARMATEURS, DETENTION_JOURS


class KaVoyage(models.Model):
    """Ordre de voyage : de la prise des conteneurs au parc de l'armateur jusqu'au retour au terre-plein (§ 5.3)."""
    _name = 'ka.voyage'
    _description = 'Ordre de voyage'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° voyage', readonly=True, copy=False, default='Nouveau')
    transporteur_id = fields.Many2one('res.partner', string='Transporteur', required=True)
    vehicule = fields.Char(string='Véhicule', required=True)
    type_transport = fields.Selection([('bitrain', 'Bi-train'), ('plateau', 'Simple plateau')],
                                      string='Type de transport', required=True, default='bitrain')
    warehouse_id = fields.Many2one('stock.warehouse', string='Usine', required=True)
    date_prise_prevue = fields.Date(string='Prise des conteneurs prévue', required=True)
    date_chargement_prevu = fields.Date(string='Chargement prévu', required=True)
    parc_armateur = fields.Char(string='Parc armateur', required=True)
    parc_terre_plein = fields.Char(string='Parc terre-plein', required=True)
    line_ids = fields.One2many('ka.voyage.line', 'voyage_id', string='Lignes du voyage')
    conteneur_ids = fields.One2many('ka.conteneur', 'voyage_id', string='Conteneurs affectés')
    nb_conteneurs = fields.Integer(compute='_compute_kpi', string='Conteneurs')
    limite_detention = fields.Date(compute='_compute_kpi', string='Limite de détention')
    limite_label = fields.Char(compute='_compute_kpi')
    # affectation
    conducteur = fields.Char(string='Conducteur')
    permis_numero = fields.Char(string='N° permis de conduire')
    permis_categorie = fields.Char(string='Catégorie du permis')
    date_depart = fields.Date(string='Date de départ')
    heure_depart = fields.Float(string='Heure de départ')
    date_prise_effective = fields.Date(string='Date de prise des conteneurs')
    priorite = fields.Selection([('normale', 'Normale'), ('urgente', 'Urgente')], default='normale', string='Priorité')
    # immobilisation du camion (RG-5.19)
    immo_motif = fields.Char(string="Motif de l'immobilisation")
    immo_jours = fields.Integer(string="Jours d'immobilisation")
    immo_montant = fields.Float(string='Frais d\'immobilisation (FCFA)', digits=(12, 0))
    po_voyage_id = fields.Many2one('purchase.order', string='Réception du voyage', readonly=True, copy=False)
    # écran 5.3 (v4.5)
    port_embarquement = fields.Char(string="Port d'embarquement", default="Port d'Abidjan")
    appartenance = fields.Selection([('tiers', 'Tiers'), ('propre', 'Propre')], string='Appartenance', default='tiers')
    trajet = fields.Char(string='Trajet', compute='_compute_trajet', store=True, readonly=False)
    nb_conteneurs_kpi = fields.Char(compute='_compute_kpi', string='Conteneurs (carte)')
    series_txt = fields.Char(compute='_compute_kpi', string='N° série conteneur(s)')
    plombs_txt = fields.Char(compute='_compute_kpi', string='N° de plomb')
    immo_constatee = fields.Selection([('non', 'Non'), ('oui', 'Oui')], string='Immobilisation constatée', default='non')
    immo_prestataire_id = fields.Many2one('res.partner', string='Prestataire concerné')
    immo_discussion = fields.Selection([('en_cours', 'En cours'), ('confirmee', 'Confirmée'), ('contestee', 'Contestée')],
                                       string='Discussion prestataire')
    immo_date_debut = fields.Date(string='Date de début')
    immo_date_fin = fields.Date(string='Date de fin')
    etape = fields.Selection([('brouillon', 'Brouillon'), ('planifie', 'Planifié'), ('en_cours', 'En cours'),
                              ('a_cloturer', 'À clôturer'), ('cloture', 'Clôturé')], compute='_compute_etape',
                             string='Étape')
    state = fields.Selection([('planifie', 'Planifié'), ('affectes', 'Conteneurs affectés'),
                              ('empotage', "En cours d'empotage"), ('a_cloturer', 'Voyage à clôturer'),
                              ('cloture', 'Clôturé')], default='planifie', string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s · Créé par la logistique' % (self.warehouse_id.name or '')

    @api.depends('state', 'line_ids')
    def _compute_etape(self):
        """Barre d'état de l'écran 5.3 : Brouillon › Planifié › En cours › À clôturer › Clôturé."""
        for v in self:
            if v.state == 'planifie':
                v.etape = 'planifie' if v.line_ids else 'brouillon'
            elif v.state in ('affectes', 'empotage'):
                v.etape = 'en_cours'
            else:
                v.etape = v.state

    @api.depends('warehouse_id', 'parc_armateur', 'parc_terre_plein')
    def _compute_trajet(self):
        for v in self:
            v.trajet = ' → '.join(x for x in (v.warehouse_id.name, v.parc_armateur, v.parc_terre_plein) if x)

    @api.onchange('immo_date_debut', 'immo_date_fin')
    def _onchange_immo_dates(self):
        if self.immo_date_debut and self.immo_date_fin:
            self.immo_jours = max((self.immo_date_fin - self.immo_date_debut).days, 0)

    @api.onchange('transporteur_id')
    def _onchange_transporteur(self):
        if self.transporteur_id and not self.immo_prestataire_id:
            self.immo_prestataire_id = self.transporteur_id

    @api.depends('conteneur_ids.armateur', 'conteneur_ids.serie', 'conteneur_ids.plomb', 'line_ids',
                 'date_prise_effective', 'date_prise_prevue')
    def _compute_kpi(self):
        for v in self:
            v.nb_conteneurs = len(v.conteneur_ids) or len(v.line_ids)
            v.nb_conteneurs_kpi = '%s ctn' % v.nb_conteneurs
            v.series_txt = ', '.join(x for x in v.conteneur_ids.mapped('serie') if x)
            v.plombs_txt = ', '.join(x for x in v.conteneur_ids.mapped('plomb') if x)
            base = v.date_prise_effective or v.date_prise_prevue
            armateurs = {c.armateur for c in v.conteneur_ids if c.armateur} or {l.sous_contrat_id.armateur for l in v.line_ids if l.sous_contrat_id.armateur}
            if base and armateurs:
                arm = sorted(armateurs, key=lambda a: DETENTION_JOURS.get(a, 30))[0]    # RG-5.8 : le plus court délai
                v.limite_detention = base + timedelta(days=DETENTION_JOURS.get(arm, 30))
                v.limite_label = 'Limite détention (%s)' % arm
            else:
                v.limite_detention = False
                v.limite_label = 'Limite détention'

    @api.constrains('line_ids', 'conteneur_ids')
    def _check_max_conteneurs(self):
        for v in self:
            if len(v.line_ids) > 2 or len(v.conteneur_ids) > 2:
                raise UserError(_('Un voyage ne peut contenir que 2 conteneurs au maximum.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.voyage')
        return super().create(vals_list)

    # ---- étape 2 : affectation des conteneurs --------------------------------------------------------------------------
    def action_valider_affectation(self):
        """Crée un article conteneur par armateur (suivi par n° de série), entré en stock au coût zéro sur le
        dépôt d'expédition de l'usine, par ajustement positif."""
        Lot = self.env['stock.lot']
        for v in self:
            if not v.conteneur_ids:
                raise UserError(_('Affectez au moins un conteneur (N° de série, plomb).'))
            if v.state != 'planifie':
                raise UserError(_('Les conteneurs de ce voyage sont déjà affectés.'))
            for c in v.conteneur_ids:
                if not (c.serie and c.plomb):
                    raise UserError(_('Le N° de série et le N° de plomb du conteneur sont obligatoires.'))
                product = v._produit_conteneur(c.armateur or 'MAERSK')
                lot = Lot.create({'name': c.serie, 'product_id': product.id, 'company_id': self.env.company.id})
                Lot.ka_move(product, lot, 1.0, product.property_stock_inventory, v.warehouse_id.lot_stock_id)
                c.lot_conteneur_id = lot
            v.write({'state': 'affectes', 'date_prise_effective': v.date_prise_effective or fields.Date.context_today(v)})

    def _produit_conteneur(self, armateur):
        Product = self.env['product.product']
        code = 'CTN-%s' % armateur.replace(' ', '')
        product = Product.search([('default_code', '=', code)], limit=1)
        return product or Product.create({'name': 'Conteneur %s' % armateur, 'default_code': code, 'type': 'consu',
                                          'is_storable': True, 'tracking': 'serial', 'standard_price': 0.0,
                                          'sale_ok': False, 'purchase_ok': False})

    # ---- clôture (RG-5.18 / RG-5.19) --------------------------------------------------------------------------------------
    def action_cloturer(self):
        for v in self:
            if v.state != 'a_cloturer':
                raise UserError(_("Le voyage ne peut être clôturé que lorsque tous ses conteneurs sont en cours d'empotage."))
            if v.immo_montant and not v.immo_motif:
                raise UserError(_("Le motif de l'immobilisation du camion est obligatoire (RG-5.19)."))
            lignes = [(self.env.ref('kode_agri_vente.product_transport'), 'Réception du voyage %s (%s)' % (
                v.name, dict(v._fields['type_transport'].selection)[v.type_transport]), 0.0)]
            if v.immo_montant:
                lignes.append((self.env.ref('kode_agri_vente.product_immobilisation'), 'Immobilisation camion — %s' % v.immo_motif, v.immo_montant))
            v.po_voyage_id = self.env['purchase.order'].create({
                'partner_id': v.transporteur_id.id, 'origin': v.name,
                'order_line': [Command.create({'product_id': p.id, 'name': lib, 'product_qty': 1, 'price_unit': m})
                               for p, lib, m in lignes]})
            v.state = 'cloture'

    def action_valider_etape(self):
        """Bouton « Valider l'étape » : étape 2 (affectation des conteneurs) puis clôture du voyage (étape 3)."""
        for v in self:
            if v.state == 'planifie':
                v.action_valider_affectation()
            elif v.state == 'a_cloturer':
                v.action_cloturer()
            elif v.state == 'cloture':
                raise UserError(_('Le voyage %s est déjà clôturé.') % v.name)
            else:
                raise UserError(_("Le voyage pourra être clôturé quand tous ses conteneurs seront en cours d'empotage."))

    def action_open_conteneurs(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Conteneurs', 'res_model': 'ka.conteneur',
                'view_mode': 'list,form', 'domain': [('voyage_id', '=', self.id)]}

    def action_imprimer(self):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Ordre de voyage'), 'type': 'success', 'sticky': False,
                           'message': _('Ordre de voyage envoyé à l\'impression.')}}


class KaVoyageLine(models.Model):
    _name = 'ka.voyage.line'
    _description = 'Ligne de voyage (planification)'

    voyage_id = fields.Many2one('ka.voyage', required=True, ondelete='cascade')
    sous_contrat_id = fields.Many2one('ka.sous.contrat', string='Sous-contrat', required=True)
    booking = fields.Char(related='sous_contrat_id.booking', string='N° booking')
    contrat_id = fields.Many2one(related='sous_contrat_id.contrat_id', string='Commande ouverte')
    quantite = fields.Integer(string='Quantité prévue', default=1, readonly=True)
    poids_net_prevu = fields.Float(compute='_compute_poids', string='Poids net prévu', digits=(8, 0))

    @api.depends('sous_contrat_id.conditionnement')
    def _compute_poids(self):
        """Poids net prévu défini selon le type d'emballage : palette 20 160 kg, vrac 21 420 kg."""
        for l in self:
            l.poids_net_prevu = 21420.0 if l.sous_contrat_id.conditionnement == 'vrac' else 20160.0
