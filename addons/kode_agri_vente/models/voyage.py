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
    state = fields.Selection([('planifie', 'Planifié'), ('affectes', 'Conteneurs affectés'),
                              ('empotage', "En cours d'empotage"), ('a_cloturer', 'Voyage à clôturer'),
                              ('cloture', 'Clôturé')], default='planifie', string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — usine %s · %s conteneurs · %s' % (self.name, self.warehouse_id.code or '', self.nb_conteneurs,
                                                       dict(self._fields['type_transport'].selection).get(self.type_transport, '').lower())

    @api.depends('conteneur_ids.armateur', 'date_prise_effective', 'date_prise_prevue')
    def _compute_kpi(self):
        for v in self:
            v.nb_conteneurs = len(v.conteneur_ids) or len(v.line_ids)
            base = v.date_prise_effective or v.date_prise_prevue
            armateurs = {c.armateur for c in v.conteneur_ids if c.armateur} or {l.sous_contrat_id.armateur for l in v.line_ids if l.sous_contrat_id.armateur}
            if base and armateurs:
                arm = sorted(armateurs, key=lambda a: DETENTION_JOURS.get(a, 30))[0]    # RG-5.8 : le plus court délai
                v.limite_detention = base + timedelta(days=DETENTION_JOURS.get(arm, 30))
                v.limite_label = 'Limite de détention %s' % arm
            else:
                v.limite_detention = False
                v.limite_label = 'Limite de détention'

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
