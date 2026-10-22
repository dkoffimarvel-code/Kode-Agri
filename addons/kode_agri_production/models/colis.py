from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import BALLES_COLIS, POIDS_BALLE, POIDS_COLIS, TEXTURES, TRACABILITE


class KaColis(models.Model):
    """Déclaration d'un colis de 1 260 kg (36 balles × 35 kg) ; un colis = un lot (point structurant n° 2)."""
    _name = 'ka.colis'
    _description = 'Déclaration de colis'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='Lot (colis)', readonly=True, copy=False, default='Nouveau')
    of_id = fields.Many2one('ka.of', string='OF', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Article', required=True,
                                 default=lambda s: s.env.ref('kode_agri_production.product_tsr', raise_if_not_found=False))
    qty = fields.Float(string='Quantité', default=POIDS_COLIS, digits=(8, 0))
    statut_id = fields.Many2one('ka.statut.colis', string='Statut')
    texture = fields.Selection(TEXTURES, string='Défaut de texture', default='conforme')
    motif = fields.Selection([('point_blanc', 'Point blanc — texture'), ('contamination', 'Contamination'),
                              ('humidite', 'Humidité'), ('autre', 'Autre')], string='Motif de déclassement')
    composition = fields.Char(default='36 balles × 35 kg', readonly=True)
    tracabilite = fields.Selection(related='of_id.tracabilite', string='Statut de traçabilité', store=True)
    location_id = fields.Many2one('stock.location', string='Emplacement',
                                  default=lambda s: s.env.ref('kode_agri_production.loc_controle', raise_if_not_found=False))
    panier_line_ids = fields.One2many('ka.colis.panier', 'colis_id', string='Paniers consommés')
    balles_total = fields.Integer(compute='_compute_balles', string='Balles consommées')
    nb_paniers = fields.Integer(compute='_compute_balles', string='Paniers consommés')
    lot_id = fields.Many2one('stock.lot', string='Lot Odoo', readonly=True, copy=False)
    state = fields.Selection([('brouillon', 'Brouillon'), ('valide', 'Validé'), ('annule', 'Annulé')],
                             default='brouillon', string='Statut')
    badge_label = fields.Char(compute='_compute_badge_label')
    of_type = fields.Selection(related='of_id.type', string="Type d'OF")
    of_state = fields.Selection(related='of_id.state', string="Statut de l'OF")
    conso_matiere = fields.Char(related='of_id.conso_matiere', string='Consommation matière mélange')
    melange_source_id = fields.Many2one(related='of_id.melange_source_id', string='Mélange source')
    balles_requises = fields.Integer(compute='_compute_libelles', string='Balles requises')
    balles_label = fields.Char(compute='_compute_libelles', string='Balles (carte)')
    paniers_label = fields.Char(compute='_compute_libelles', string='Paniers (carte)')
    lot_label = fields.Char(compute='_compute_libelles', string='N° de lot')
    statut_label = fields.Char(compute='_compute_libelles', string='Statut colis')
    titre_label = fields.Char(compute='_compute_libelles', string='Libellé du titre')

    @api.depends('name')
    def _compute_display_name(self):
        for c in self:
            c.display_name = 'Colis %s' % (c.name or '')

    @api.depends('panier_line_ids.balles', 'panier_line_ids.panier_id', 'lot_id', 'statut_id', 'of_id.type', 'name')
    def _compute_libelles(self):
        for c in self:
            nb = len(c.panier_line_ids.panier_id)
            c.balles_requises = BALLES_COLIS
            c.balles_label = '%d × %d' % (c.balles_total or BALLES_COLIS, POIDS_BALLE)
            c.paniers_label = '%d panier%s' % (nb, 's' if nb > 1 else '')
            c.lot_label = c.lot_id.name or '%s (auto)' % (c.name or '')
            c.statut_label = ('%s — %s' % (c.statut_id.article_code or '', c.statut_id.name)) if c.statut_id else ''
            c.titre_label = "N° de série du colis d'essai" if c.of_id.type == 'essai' else 'N° de série du colis'

    def _ka_subtitle(self):
        self.ensure_one()
        poids = '{:,.0f}'.format(self.qty).replace(',', ' ')
        nature = "Colis d'essai" if self.of_id.type == 'essai' else 'Colis sérialisé'
        return '%s — %s kg = %d balles de %d kg' % (nature, poids, BALLES_COLIS, POIDS_BALLE)

    @api.depends('panier_line_ids.balles')
    def _compute_balles(self):
        for c in self:
            c.balles_total = sum(c.panier_line_ids.mapped('balles'))
            c.nb_paniers = len(c.panier_line_ids.panier_id)

    @api.depends('texture', 'state', 'motif')
    def _compute_badge_label(self):
        labels = dict(self._fields['texture'].selection)
        for c in self:
            if c.texture and c.texture != 'conforme':
                c.badge_label = 'Quarantaine — %s' % labels[c.texture]
            else:
                c.badge_label = {'brouillon': 'En saisie', 'valide': 'Validé', 'annule': 'Annulé'}[c.state]

    @api.onchange('motif')
    def _onchange_motif(self):
        """RG-4.10 : le statut de colis découle automatiquement du défaut."""
        mapping = {'point_blanc': 'points_blancs', 'contamination': 'contamine', 'humidite': 'humide',
                   'autre': 'autre'}
        self.texture = mapping.get(self.motif, 'conforme')
        if self.texture != 'conforme':
            self.statut_id = self.env['ka.statut.colis'].search([('defaut', '=', True), (
                'name', 'ilike', dict(TEXTURES)[self.texture])], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                of = self.env['ka.of'].browse(vals.get('of_id'))
                code = 'ka.colis.essai' if of.exists() and of.type == 'essai' else 'ka.colis'
                vals['name'] = self.env['ir.sequence'].next_by_code(code) or \
                    self.env['ir.sequence'].next_by_code('ka.colis')
        return super().create(vals_list)

    def action_valider(self):
        for c in self:
            if c.state != 'brouillon':
                continue
            if c.balles_total != BALLES_COLIS:
                raise UserError(_('Le colis doit consommer exactement %s balles (RG-4.6) : %s saisies.') % (
                    BALLES_COLIS, c.balles_total))
            for line in c.panier_line_ids:
                if line.balles > line.balles_avant:
                    raise UserError(_('Le panier %s ne dispose que de %s balles.') % (
                        line.panier_id.name, line.balles_avant))
            if c.texture != 'conforme' and not c.motif:
                raise UserError(_('Un motif de déclassement est obligatoire (RG-4.10).'))
            lot = self.env['stock.lot'].create({
                'name': c.name, 'product_id': c.product_id.id, 'company_id': self.env.company.id,
                'ka_est_colis': True, 'ka_tracabilite': c.tracabilite, 'ka_etat': 'Q',
                'ka_statut_id': c.statut_id.id or self.env['ka.statut.colis'].search(
                    [('article_code', '=', 'TSR'), ('defaut', '=', False)], limit=1).id,
                'ka_motif': dict(self._fields['motif'].selection).get(c.motif, '')})
            controle = c.location_id or self.env.ref('kode_agri_production.loc_controle')
            self.env['stock.lot'].ka_move(c.product_id, lot, c.qty, c.product_id.property_stock_production, controle)
            c.write({'lot_id': lot.id, 'state': 'valide'})
            c.of_id.state = 'produit' if c.of_id.state == 'lance' else c.of_id.state

    def action_declasser(self):
        """RG-4.10 : déclassement direct à la production — le colis passe en quarantaine (statut du défaut)."""
        for c in self:
            if not c.motif:
                c.motif = 'point_blanc'
            c._onchange_motif()
            if c.lot_id:
                c.lot_id.write({'ka_etat': 'Q', 'ka_statut_id': c.statut_id.id or c.lot_id.ka_statut_id.id,
                                'ka_motif': dict(self._fields['motif'].selection).get(c.motif, '')})

    def action_voir_paniers(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Paniers consommés', 'res_model': 'ka.panier',
                'view_mode': 'list,form', 'domain': [('id', 'in', self.panier_line_ids.panier_id.ids)]}

    def action_annuler(self):
        for c in self:
            if c.state == 'valide':
                raise UserError(_('Un colis validé ne peut pas être annulé : utilisez le reconditionnement.'))
            c.state = 'annule'

    def action_etiquette(self):
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Étiquette'), 'message': _('Étiquette du colis %s envoyée à l\'imprimante.') % self.name,
                           'type': 'success', 'sticky': False}}


class KaColisPanier(models.Model):
    _name = 'ka.colis.panier'
    _description = 'Balles de panier consommées par un colis'
    _order = 'id'

    colis_id = fields.Many2one('ka.colis', required=True, ondelete='cascade')
    panier_id = fields.Many2one('ka.panier', string='N° panier', required=True,
                                domain="[('of_id', '=', parent.of_id), ('state', '=', 'valide')]")
    chrono = fields.Char(related='panier_id.chrono', string='N° chrono')
    panier_name = fields.Char(related='panier_id.name', string='N° panier')
    sechoir_id = fields.Many2one(related='panier_id.sechoir_id', string='Séchoir')
    balles_avant = fields.Integer(compute='_compute_balles', string='Balles avant')
    balles = fields.Integer(string='Balles utilisées')
    balles_restantes = fields.Integer(compute='_compute_balles', string='Balles restantes')

    @api.depends('panier_id.nb_balles', 'panier_id.colis_line_ids.balles', 'balles')
    def _compute_balles(self):
        for l in self:
            autres = l.panier_id.colis_line_ids.filtered(
                lambda x: x.id != l._origin.id and x.colis_id.state != 'annule' and (not l._origin.id or x.id < l._origin.id))
            l.balles_avant = l.panier_id.nb_balles - sum(autres.mapped('balles'))
            l.balles_restantes = l.balles_avant - l.balles
