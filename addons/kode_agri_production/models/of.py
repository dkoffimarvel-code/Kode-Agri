from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import POIDS_COLIS, TRACABILITE, ka_param


class KaOf(models.Model):
    """Ordre de fabrication Kode Agri : mélange, production, essai ou reclassement (§ 4.2)."""
    _name = 'ka.of'
    _description = 'Ordre de fabrication'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° OF', readonly=True, copy=False, default='Nouveau')
    type = fields.Selection([('melange', 'MEL — Mélange'), ('production', 'PRD — Production'),
                             ('essai', 'ESS — Essai'), ('reclassement', 'RCL — Reclassement')],
                            string="Type d'OF", required=True, default='production')
    state = fields.Selection([('planifie', 'Planifié'), ('lance', 'Lancé'), ('en_essai', 'En essai'),
                              ('produit', 'Produit'), ('specifie', 'Spécifié'), ('solde', 'Soldé')],
                             default='planifie', string='Statut', tracking=True)
    badge_label = fields.Char(compute='_compute_badge_label')
    warehouse_id = fields.Many2one('stock.warehouse', string='Site',
                                   default=lambda s: s.env['stock.warehouse'].search(
                                       [('company_id', '=', s.env.company.id)], limit=1))
    product_id = fields.Many2one('product.product', string='Article', required=True)
    qty = fields.Float(string='Quantité lancée', digits=(12, 0))
    date_lancement = fields.Date(string='Date de lancement')
    date_prevue = fields.Date(string='Date prévue')
    mode_conso = fields.Selection([('manuelle', 'Manuelle'), ('auto', 'Automatique (DRC réel)')],
                                  string='Mode de consommation', default='auto')
    atelier = fields.Selection([('broyage', 'Broyage / homogénéisation'), ('pilote', 'Laboratoire pilote'),
                                ('production', 'Production')], string='Atelier')
    tracabilite = fields.Selection(TRACABILITE, string='Statut de traçabilité',
                                   compute='_compute_tracabilite', store=True, readonly=False)
    note = fields.Char()
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)

    # mélange
    lot_ids = fields.One2many('ka.of.lot', 'of_id', string='Matières — lots de fond de tasse alloués')
    nb_lots = fields.Integer(compute='_compute_melange', string='Lots FDT')
    drc_reel = fields.Float(compute='_compute_melange', string='DRC réel moyen', digits=(5, 1), store=True)
    cout_matiere = fields.Monetary(compute='_compute_melange', string='Coût matière', store=True)
    lot_melange = fields.Char(compute='_compute_lot_melange', string='Lot de mélange')

    # production / essai
    grade_vise = fields.Selection([('TSR10', 'TSR10 (objectif)'), ('TSR20', 'TSR20 (objectif)'),
                                   ('OFFSPECS', 'OFFSPECS')], string='Grade visé')
    poids_colis = fields.Float(string="Poids net d'un colis", default=POIDS_COLIS, digits=(8, 0))
    composition = fields.Char(default='36 balles × 35 kg', readonly=True)
    melange_ids = fields.One2many('ka.of.melange', 'of_id', string='Mélange à consommer')
    qty_humide = fields.Float(compute='_compute_estimation', string='Quantité humide affectée', digits=(12, 0), store=True)
    drc_ref = fields.Float(string='DRC de référence (%)', digits=(5, 1),
                           default=lambda s: ka_param(s.env, 'drc_reference', 60.0))
    tsr_estime = fields.Float(compute='_compute_estimation', string='TSR estimé', digits=(12, 0), store=True)
    nb_colis_estime = fields.Integer(compute='_compute_estimation', string='Nombre de colis estimé', store=True)
    bains_par_panier = fields.Integer(string='Bains par panier', default=4)
    melange_source_id = fields.Many2one('ka.of', string='Mélange source', domain=[('type', '=', 'melange')])
    conso_matiere = fields.Char(string='Consommation matière', default='Non — pour mémoire', readonly=True)
    lot_melange_source = fields.Char(related='melange_source_id.lot_melange', string='Lot de mélange')
    echantillon_kg = fields.Float(string='Échantillon prévu', digits=(8, 0))
    panier_ids = fields.One2many('ka.panier', 'of_id', string='Paniers')
    colis_ids = fields.One2many('ka.colis', 'of_id', string='Colis')
    nb_paniers = fields.Integer(compute='_compute_counts')
    nb_colis = fields.Integer(compute='_compute_counts')

    def _ka_subtitle(self):
        self.ensure_one()
        art = self.product_id.display_name or ''
        if self.type == 'melange':
            return '%s — article %s (mélange homogène)' % (self.name, self.product_id.default_code or art)
        if self.type == 'essai':
            return "%s — OF d'essai sur échantillon de mélange" % self.name
        if self.type == 'reclassement':
            return '%s — reclassement 1 pour 1' % self.name
        return '%s — production de colis TSR (non spécifié)' % self.name

    @api.model
    def _poids_colis(self):
        return POIDS_COLIS

    @api.depends('state', 'type')
    def _compute_badge_label(self):
        for of in self:
            of.badge_label = {'planifie': 'En création', 'lance': 'Lancé', 'en_essai': 'En essai',
                              'produit': 'Produit', 'specifie': 'Spécifié', 'solde': 'Soldé'}[of.state]

    @api.depends('lot_ids.tracabilite', 'melange_ids.melange_of_id.tracabilite', 'melange_source_id.tracabilite')
    def _compute_tracabilite(self):
        """Un seul lot ou mélange NON EUDR rend l'ensemble NON EUDR (ET logique)."""
        for of in self:
            origines = (of.lot_ids.mapped('tracabilite') + of.melange_ids.melange_of_id.mapped('tracabilite')
                        + of.melange_source_id.mapped('tracabilite'))
            of.tracabilite = 'non_eudr' if 'non_eudr' in origines else 'eudr'

    @api.depends('lot_ids.qty', 'lot_ids.drc', 'lot_ids.valorisation')
    def _compute_melange(self):
        for of in self:
            total = sum(of.lot_ids.mapped('qty'))
            of.nb_lots = len(of.lot_ids)
            of.drc_reel = (sum(l.qty * l.drc for l in of.lot_ids) / total) if total else 0.0
            of.cout_matiere = sum(of.lot_ids.mapped('valorisation'))

    @api.depends('melange_ids.qty_humide', 'melange_ids.drc_ref', 'melange_ids.tsr_estime', 'poids_colis')
    def _compute_estimation(self):
        """RG-4.8 : TSR estimé = quantité humide × DRC de référence."""
        for of in self:
            of.qty_humide = sum(of.melange_ids.mapped('qty_humide'))
            of.tsr_estime = sum(of.melange_ids.mapped('tsr_estime'))
            of.nb_colis_estime = round(of.tsr_estime / of.poids_colis) if of.poids_colis else 0

    @api.depends('melange_ids')
    def _compute_lot_melange(self):
        for of in self:
            of.lot_melange = of._lot_melange_name()

    def _lot_melange_name(self):
        self.ensure_one()
        suffix = (self.name or '').split('-')[-1]
        return 'MEL-%s-%s' % (fields.Date.today().year, suffix)

    @api.depends('panier_ids', 'colis_ids')
    def _compute_counts(self):
        for of in self:
            of.nb_paniers = len(of.panier_ids)
            of.nb_colis = len(of.colis_ids)

    @api.model_create_multi
    def create(self, vals_list):
        seqs = {'melange': 'ka.of.melange', 'production': 'ka.of.production', 'essai': 'ka.of.essai',
                'reclassement': 'ka.of.reclassement'}
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code(seqs[vals.get('type', 'production')])
        return super().create(vals_list)

    # ---- actions ---------------------------------------------------------------------------------
    def action_lancer(self):
        for of in self:
            if of.state != 'planifie':
                raise UserError(_('Seul un OF planifié peut être lancé.'))
            if of.type == 'production' and not of.melange_ids:
                raise UserError(_("Affectez au moins un mélange à l'OF de production avant de le lancer."))
            if of.type == 'essai' and not of.melange_source_id:
                raise UserError(_("Renseignez le mélange source de l'OF d'essai."))
            of.write({'state': 'en_essai' if of.type == 'essai' else 'lance',
                      'date_lancement': fields.Date.context_today(of)})

    def action_allocation(self):
        """Allocation détaillée des lots : ouvre la liste des lots alloués."""
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Allocation détaillée des lots',
                'res_model': 'ka.of.lot', 'view_mode': 'list', 'domain': [('of_id', '=', self.id)],
                'context': {'default_of_id': self.id}}

    def action_consommer_fdt(self):
        """Consomme le fond de tasse des lots alloués (mouvements valorisés vers la production)."""
        self.ensure_one()
        if self.type != 'melange':
            raise UserError(_("La consommation du fond de tasse se fait sur l'OF de mélange."))
        if not self.lot_ids:
            raise UserError(_('Aucun lot de fond de tasse alloué.'))
        for ligne in self.lot_ids.filtered(lambda l: not l.consomme):
            ligne._consommer()
        self.message_post(body=_('Fond de tasse consommé : %s lot(s).') % len(self.lot_ids))

    def action_solder(self):
        for of in self:
            if of.type == 'production' and of.melange_ids.melange_of_id.filtered(
                    lambda m: m.mode_conso == 'manuelle' and m.state != 'solde'):
                raise UserError(_("Consommation manuelle : l'OF de mélange lié doit d'abord être consommé "
                                  "et soldé."))
            if of.panier_ids.filtered(lambda p: p.state not in ('valide', 'cloture')) or \
                    of.colis_ids.filtered(lambda c: c.state == 'brouillon'):
                raise UserError(_("Tous les paniers et colis de l'OF doivent être déclarés et validés (§ 4.2.4)."))
            of.state = 'solde'
            of.melange_ids.melange_of_id.filtered(lambda m: m.state != 'solde').write({'state': 'solde'})
            if of.type == 'essai':
                of._solder_essai()

    def _solder_essai(self):
        """RG-4.9 : l'essai consomme l'échantillon du mélange à la clôture, sans mouvement de stock."""
        self.ensure_one()
        self.message_post(body=_('Échantillon de %s kg consommé « pour mémoire » sur %s.') % (
            self.echantillon_kg, self.melange_source_id.name))

    def action_declarer_paniers(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Déclaration des paniers', 'res_model': 'ka.panier',
                'view_mode': 'list,form', 'domain': [('of_id', '=', self.id)],
                'context': {'default_of_id': self.id}}

    def action_declarer_colis(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Déclaration des colis', 'res_model': 'ka.colis',
                'view_mode': 'list,form', 'domain': [('of_id', '=', self.id)],
                'context': {'default_of_id': self.id}}

    def action_tracabilite(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Traçabilité amont / aval', 'res_model': 'stock.lot',
                'view_mode': 'list,form', 'domain': [('id', 'in', self.lot_ids.lot_id.ids)]}

    def action_essais_drc(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Essais DRC des lots', 'res_model': 'ka.drc.essai',
                'view_mode': 'list,form', 'domain': [('lot_id', 'in', self.lot_ids.lot_id.ids)]}

    # ---- DRC réel (clôture liée mélange / production / essai) ----------------------------------------
    def ka_calculer_drc_reel(self):
        """DRC réel = production réelle (sec) / consommation humide ; met à jour le DRC des lots."""
        for of in self.filtered(lambda o: o.type == 'production'):
            humide = of.qty_humide or sum(of.melange_ids.mapped('qty_humide'))
            sec = sum(of.colis_ids.filtered(lambda c: c.state == 'valide').mapped('qty'))
            if humide and sec:
                drc = round(sec / humide * 100.0, 2)
                for melange in of.melange_ids.melange_of_id:
                    melange.lot_ids.lot_id.ka_set_drc(drc, _('DRC réel de %s') % of.name)


class KaOfLot(models.Model):
    _name = 'ka.of.lot'
    _description = "Lot de fond de tasse alloué à un OF de mélange"

    of_id = fields.Many2one('ka.of', required=True, ondelete='cascade')
    lot_id = fields.Many2one('stock.lot', string='Lot', required=True, domain="[('ka_est_colis', '=', False)]")
    partner_id = fields.Many2one('res.partner', string="Fournisseur d'origine")
    godets = fields.Integer(string='Godets', default=1, help="Part de godets prélevés par alimentation (1 godet ≈ 1 t).")
    qty = fields.Float(string='Quantité (kg)', digits=(12, 0))
    drc = fields.Float(string='Titre (DRC)', digits=(5, 0))
    cout_kg = fields.Float(string='Coût / kg', digits=(10, 2))
    currency_id = fields.Many2one(related='of_id.currency_id')
    valorisation = fields.Monetary(string='Valorisation (FCFA)', compute='_compute_valorisation', store=True)
    tracabilite = fields.Selection(related='lot_id.ka_tracabilite', string='Traçabilité')
    consomme = fields.Boolean(readonly=True)

    @api.onchange('lot_id')
    def _onchange_lot(self):
        if self.lot_id:
            self.drc = self.lot_id.ka_drc or ka_param(self.env, 'drc_reference', 60.0)
            self.qty = self.lot_id.product_qty
            self.cout_kg = self.lot_id.product_id.standard_price
            ticket = self.env['ka.ticket'].search([('lot_name', '=', self.lot_id.name)], limit=1)
            self.partner_id = ticket.partner_id

    @api.depends('qty', 'cout_kg')
    def _compute_valorisation(self):
        for l in self:
            l.valorisation = l.qty * l.cout_kg

    def _consommer(self):
        for l in self:
            src = l.lot_id.ka_location()
            if not src:
                raise UserError(_('Le lot %s n\'a pas de stock disponible.') % l.lot_id.name)
            prod = l.lot_id.product_id.property_stock_production
            self.env['stock.lot'].ka_move(l.lot_id.product_id, l.lot_id, l.qty, src, prod)
            l.consomme = True


class KaOfMelange(models.Model):
    _name = 'ka.of.melange'
    _description = "Mélange affecté à un OF de production"

    of_id = fields.Many2one('ka.of', required=True, ondelete='cascade')
    melange_of_id = fields.Many2one('ka.of', string='OF de mélange', required=True,
                                    domain=[('type', '=', 'melange')])
    lot_melange = fields.Char(related='melange_of_id.lot_melange', string='Lot de mélange')
    qty_humide = fields.Float(string='Quantité humide (kg)', digits=(12, 0))
    drc_ref = fields.Float(string='DRC de référence', digits=(5, 0),
                           default=lambda s: ka_param(s.env, 'drc_reference', 60.0))
    tsr_estime = fields.Float(string='TSR estimé (kg)', compute='_compute_tsr', store=True, digits=(12, 0))

    @api.depends('qty_humide', 'drc_ref')
    def _compute_tsr(self):
        for m in self:
            m.tsr_estime = m.qty_humide * m.drc_ref / 100.0
