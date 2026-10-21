from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.kode_agri_maintenance.models.equipement import nb

TYPES = [('revision', 'Révision'), ('vidange', 'Vidange'), ('pneumatiques', 'Pneumatiques'), ('reparation', 'Réparation'),
         ('visite', 'Visite programmée'), ('autre', 'Autre')]


class KaFloPlan(models.Model):
    """Plan d'entretien de la flotte déclenché au kilométrage ou aux heures-moteur (RG-11.1)."""
    _name = 'ka.flo.plan'
    _description = "Plan d'entretien de véhicule"
    _order = 'vehicule_id, prochaine'

    vehicule_id = fields.Many2one('ka.flo.vehicule', string='Véhicule', required=True, ondelete='cascade')
    intitule = fields.Char(string='Intitulé', required=True, help='Ex. Révision des 150 000 km')
    type = fields.Selection(TYPES, string='Type', required=True, default='revision')
    periodicite = fields.Float(string='Périodicité (km ou h)', required=True, digits=(12, 0))
    derniere = fields.Float(string='Dernière exécution (compteur)', digits=(12, 0))
    prochaine = fields.Float(compute='_compute_prochaine', store=True, string='Prochain seuil', digits=(12, 0))
    anticipation = fields.Float(string='Anticipation', default=2000, digits=(10, 0),
                                help="Avance de génération de l'ordre d'entretien, en km (ou heures)")
    duree_estimee = fields.Float(string='Durée estimée (h)', digits=(6, 1))
    operation_ids = fields.One2many('ka.flo.plan.operation', 'plan_id', string='Opérations et pièces')
    entretien_ids = fields.One2many('ka.flo.entretien', 'plan_id', string='Ordres générés')
    state = fields.Selection([('brouillon', 'Brouillon'), ('actif', 'Actif')], default='actif', string='Statut')

    @api.depends('derniere', 'periodicite')
    def _compute_prochaine(self):
        for p in self:
            p.prochaine = p.derniere + p.periodicite

    def verifier_echeances(self):
        for p in self.filtered(lambda x: x.state == 'actif' and x.periodicite):
            if p.vehicule_id.odometre >= p.prochaine - p.anticipation and \
                    not p.entretien_ids.filtered(lambda e: e.state not in ('cloture', 'annule')):
                p._generer()

    def _generer(self):
        self.ensure_one()
        v = self.vehicule_id
        e = self.env['ka.flo.entretien'].create({
            'vehicule_id': v.id, 'plan_id': self.id, 'type': self.type, 'declencheur': 'kilometrage' if v.unite_compteur == 'km' else 'heures',
            'seuil': self.prochaine, 'km_declenchement': v.odometre, 'objet': self.intitule, 'duree_estimee': self.duree_estimee,
            'equipe_id': v.equipe_id.id, 'ligne_ids': [Command.create({'operation': o.name, 'product_id': o.product_id.id,
                                                                       'quantite': o.quantite}) for o in self.operation_ids]})
        v.message_post(body=_("Ordre d'entretien %s généré au compteur %s (RG-11.1).") % (e.name, nb(v.odometre, v.unite_compteur)))
        return e

    def action_generer(self):
        for p in self:
            p._generer()

    @api.model
    def _cron_echeances(self):
        self.search([('state', '=', 'actif')]).verifier_echeances()


class KaFloPlanOperation(models.Model):
    _name = 'ka.flo.plan.operation'
    _description = "Opération de plan d'entretien"
    _order = 'sequence, id'

    plan_id = fields.Many2one('ka.flo.plan', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Opération', required=True)
    product_id = fields.Many2one('product.product', string='Pièce / consommable')
    quantite = fields.Float(string='Quantité', digits=(10, 2), default=1.0)


class KaFloEntretien(models.Model):
    """Ordre d'entretien de la flotte (§ 11.2) : préventif au compteur ou correctif ; réalisé à l'atelier interne
    (module 10) ou confié à un garage externe, avec le circuit achats du § 11.2.1. La clôture met à jour le compteur et
    l'historique du véhicule et impute le coût au coût de revient kilométrique (module 9)."""
    _name = 'ka.flo.entretien'
    _description = "Ordre d'entretien de véhicule"
    _inherit = ['ka.document', 'ka.flo.achat', 'mail.thread', 'mail.activity.mixin']
    _order = 'date_prevue desc, name desc'

    name = fields.Char(string='N° ordre', readonly=True, copy=False, default='Nouveau')
    vehicule_id = fields.Many2one('ka.flo.vehicule', string='Véhicule', required=True)
    objet = fields.Char(string='Objet', required=True, default='Entretien')
    type = fields.Selection(TYPES, string='Type', required=True, default='revision')
    declencheur = fields.Selection([('kilometrage', 'Kilométrage'), ('heures', 'Heures-moteur'), ('panne', 'Panne signalée'),
                                    ('visite', 'Visite programmée')], string='Déclencheur', required=True, default='kilometrage')
    declencheur_txt = fields.Char(compute='_compute_txt', string='Déclencheur')
    seuil = fields.Float(string='Seuil', digits=(12, 0))
    seuil_txt = fields.Char(compute='_compute_txt', string='Seuil')
    km_declenchement = fields.Float(string='Km au déclenchement', digits=(12, 0))
    km_cloture = fields.Float(string='Compteur à la clôture', digits=(12, 0))
    date_prevue = fields.Date(string='Date prévue', default=fields.Date.context_today)
    date_cloture = fields.Date(string='Date de clôture', readonly=True, copy=False)
    realisation = fields.Selection([('interne', 'Atelier interne'), ('garage', 'Garage externe')], string='Réalisation',
                                   default='interne', required=True)
    equipe_id = fields.Many2one('ka.mnt.equipe', string='Atelier interne')
    garage_txt = fields.Char(compute='_compute_txt', string='Garage / atelier')
    duree_estimee = fields.Float(string='Durée estimée (h)', digits=(6, 1))
    duree_txt = fields.Char(compute='_compute_txt', string='Durée estimée')
    plan_id = fields.Many2one('ka.flo.plan', string="Plan d'entretien", readonly=True)
    ligne_ids = fields.One2many('ka.flo.entretien.ligne', 'entretien_id', string='Opérations et pièces')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    cout_total = fields.Monetary(compute='_compute_cout', string="Coût de l'entretien", store=True)
    cout_txt = fields.Char(compute='_compute_cout', string="Coût de l'entretien")
    titre = fields.Char(compute='_compute_txt')
    imputation_faite = fields.Boolean(readonly=True, copy=False)
    state = fields.Selection([('prevu', 'Prévu'), ('planifie', 'Planifié'), ('en_cours', 'En cours'), ('cloture', 'Clôturé'),
                              ('annule', 'Annulé')], default='prevu', string='Statut', tracking=True)

    @api.depends('name', 'vehicule_id')
    def _compute_display_name(self):
        for e in self:
            e.display_name = '%s — %s' % (e.name, e.vehicule_id.name or '')

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s · %s' % (self.vehicule_id.name or '', (self.objet or '').lower())

    @api.depends('declencheur', 'seuil', 'realisation', 'equipe_id', 'prestataire_id', 'duree_estimee', 'vehicule_id.unite_compteur', 'name')
    def _compute_txt(self):
        decl = dict(self._fields['declencheur'].selection)
        for e in self:
            u = e.vehicule_id.unite_compteur or 'km'
            e.titre = _("Ordre d'entretien %s") % (e.name or '')
            e.seuil_txt = nb(e.seuil, u) if e.seuil else ''
            e.declencheur_txt = '%s (%s)' % (decl.get(e.declencheur, ''), e.seuil_txt) if e.seuil else decl.get(e.declencheur, '')
            e.garage_txt = (e.equipe_id.name or _('Atelier maintenance')) if e.realisation == 'interne' else (e.prestataire_id.name or _('Garage externe'))
            e.duree_txt = ('%g h' % e.duree_estimee).replace('.', ',') if e.duree_estimee else ''

    @api.depends('ligne_ids.cout')
    def _compute_cout(self):
        for e in self:
            e.cout_total = sum(e.ligne_ids.mapped('cout'))
            e.cout_txt = '%s FCFA' % nb(e.cout_total)

    @api.onchange('realisation')
    def _onchange_realisation(self):
        self.externe = self.realisation == 'garage'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.flo.entretien')
            if vals.get('realisation') == 'garage':
                vals['externe'] = True
        return super().create(vals_list)

    def action_planifier(self):
        """Qualifie l'ordre : interne (atelier) ou externe (garage) ; un ordre externe déclenche le circuit achats."""
        for e in self:
            if e.state != 'prevu':
                raise UserError(_("L'ordre est déjà planifié."))
            if e.realisation == 'garage':
                e.externe = True
                if not e.commande_id and not e.da_id:
                    e._ka_lancer_achat(_('Entretien %s — %s') % (e.vehicule_id.name, e.objet), e.cout_total)
            e.state = 'planifie'

    def action_demarrer(self):
        """L'exécution peut démarrer avant l'aboutissement du circuit achats si l'urgence le justifie (RG-11.2)."""
        for e in self:
            if e.state not in ('prevu', 'planifie'):
                raise UserError(_("L'ordre est déjà en cours ou clos."))
            e.state = 'en_cours'
            e.vehicule_id.state = 'en_entretien'

    def action_cloturer(self):
        for e in self:
            if e.state not in ('planifie', 'en_cours'):
                raise UserError(_("Seul un ordre planifié ou en cours peut être clôturé."))
            e._ka_controler_commande()
            e._ka_reception_auto(e.name)
            e._sortie_pieces()
            e.write({'state': 'cloture', 'date_cloture': fields.Date.context_today(self)})
            v = e.vehicule_id
            v.maj_compteur(e.km_cloture or e.km_declenchement, e.name)
            if e.plan_id:
                e.plan_id.derniere = e.seuil or e.km_cloture or v.odometre
            if v.state == 'en_entretien':
                v.state = 'disponible'
            if not e.imputation_faite:
                e._ka_imputer(v, e.cout_total, '%s — %s' % (e.name, v.name), e.date_cloture)
                e.imputation_faite = True

    def _sortie_pieces(self):
        lignes = self.ligne_ids.filtered(lambda l: l.product_id.is_storable and not l.move_id and l.quantite > 0
                                         and self.realisation == 'interne')
        if not lignes:
            return
        wh = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        dest = self.env.ref('kode_agri_maintenance.location_conso_mnt')
        for l in lignes:
            vals = {'product_id': l.product_id.id, 'product_uom_qty': l.quantite, 'product_uom': l.product_id.uom_id.id,
                    'location_id': wh.lot_stock_id.id, 'location_dest_id': dest.id, 'origin': self.name}
            if 'name' in self.env['stock.move']._fields:
                vals['name'] = '%s — %s' % (self.name, l.product_id.display_name)
            move = self.env['stock.move'].create(vals)
            move._action_confirm()
            move._action_assign()
            move.quantity = l.quantite
            move.picked = True
            move._action_done()
            l.move_id = move

    def action_annuler(self):
        for e in self:
            if e.state == 'cloture':
                raise UserError(_('Un ordre clôturé ne peut pas être annulé.'))
            e.state = 'annule'

    def action_open_vehicule(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.flo.vehicule', 'res_id': self.vehicule_id.id, 'view_mode': 'form'}

    def action_open_commande(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.commande', 'res_id': self.commande_id.id, 'view_mode': 'form'}


class KaFloEntretienLigne(models.Model):
    _name = 'ka.flo.entretien.ligne'
    _description = "Ligne d'ordre d'entretien"
    _order = 'sequence, id'

    entretien_id = fields.Many2one('ka.flo.entretien', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    operation = fields.Char(string='Opération', required=True)
    product_id = fields.Many2one('product.product', string='Pièce / consommable')
    quantite = fields.Float(string='Quantité', digits=(10, 2), default=1.0)
    quantite_txt = fields.Char(compute='_compute_qte', string='Quantité')
    currency_id = fields.Many2one(related='entretien_id.currency_id')
    prix_unitaire = fields.Monetary(string='Prix unitaire', compute='_compute_prix', store=True, readonly=False)
    cout = fields.Monetary(compute='_compute_cout', string='Coût', store=True, readonly=False)
    move_id = fields.Many2one('stock.move', string='Sortie magasin', readonly=True, copy=False)

    @api.depends('product_id')
    def _compute_prix(self):
        for l in self:
            l.prix_unitaire = l.product_id.standard_price

    @api.depends('quantite', 'prix_unitaire')
    def _compute_cout(self):
        for l in self:
            l.cout = l.quantite * l.prix_unitaire

    @api.depends('quantite', 'product_id.uom_id')
    def _compute_qte(self):
        for l in self:
            u = l.product_id.uom_id.name or ''
            l.quantite_txt = ('%g %s' % (l.quantite, u if u.lower() not in ('unité', 'unités', 'units', 'unit') else '')).replace('.', ',').strip()
