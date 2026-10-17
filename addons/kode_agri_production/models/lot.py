from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import TRACABILITE


class KaStatutColis(models.Model):
    """Statuts de colis paramétrables par article (§ 4.2.6)."""
    _name = 'ka.statut.colis'
    _description = 'Statut de colis'
    _order = 'article_code, sequence, id'

    name = fields.Char(string='Statut', required=True)
    article_code = fields.Char(string='Article', help='Code article (TSR, TSR10, TSR20, OFFSPECS)')
    sequence = fields.Integer(default=10)
    defaut = fields.Boolean(string='Défaut de texture', help='Place le colis en quarantaine (statut Q).')
    code_court = fields.Char(string='Code court', help='Ex. QPB pour Points blancs')

    @api.depends('name', 'defaut', 'code_court')
    def _compute_display_name(self):
        for s in self:
            s.display_name = ('Q — sous-statut %s %s' % (s.code_court or '', s.name)).replace('  ', ' ') if s.defaut else s.name


class KaDrcHisto(models.Model):
    _name = 'ka.drc.histo'
    _description = 'Historique du DRC d’un lot'
    _order = 'date desc, id desc'

    lot_id = fields.Many2one('stock.lot', required=True, ondelete='cascade')
    date = fields.Datetime(default=fields.Datetime.now)
    drc = fields.Float(string='DRC (%)', digits=(5, 2))
    source = fields.Char(string='Source')


class StockLot(models.Model):
    _inherit = 'stock.lot'

    ka_drc = fields.Float(string='DRC (%)', digits=(5, 2), tracking=False,
                          help="Titre en caoutchouc sec du lot (point structurant n° 1).")
    ka_poids_sec = fields.Float(string='Poids sec (kg)', compute='_compute_ka_poids_sec', digits=(12, 1))
    ka_drc_histo_ids = fields.One2many('ka.drc.histo', 'lot_id', string='Historique DRC')
    ka_tracabilite = fields.Selection(TRACABILITE, string='Statut de traçabilité', default='eudr')
    ka_etat = fields.Selection([('A', 'A — Accepté'), ('Q', 'Q — Quarantaine')], string='Statut stock')
    ka_statut_id = fields.Many2one('ka.statut.colis', string='Statut de colis')
    ka_motif = fields.Char(string='Motif de déclassement')
    ka_spec_id = fields.Many2one('ka.spec', string='Spécification', copy=False)
    ka_est_colis = fields.Boolean(string='Colis de 1 260 kg')

    @api.depends('ka_drc', 'product_qty')
    def _compute_ka_poids_sec(self):
        for lot in self:
            lot.ka_poids_sec = lot.product_qty * lot.ka_drc / 100.0

    def ka_set_drc(self, drc, source):
        """Met à jour le DRC du lot avec historisation (point structurant n° 1)."""
        for lot in self:
            lot.write({'ka_drc': drc, 'ka_drc_histo_ids': [Command.create({'drc': drc, 'source': source})]})

    def ka_etat_label(self):
        self.ensure_one()
        if not self.ka_etat:
            return ''
        return '%s — %s' % (self.ka_etat, self.ka_statut_id.name or self.product_id.name)

    # ---- mouvements de stock ------------------------------------------------------------------
    @api.model
    def ka_move(self, product, lot, qty, src, dest):
        """Mouvement valorisé standard d'un lot entre deux emplacements."""
        Move = self.env['stock.move']
        vals = {
            'product_id': product.id, 'product_uom_qty': qty, 'product_uom': product.uom_id.id,
            'location_id': src.id, 'location_dest_id': dest.id, 'company_id': self.env.company.id,
            'move_line_ids': [Command.create({
                'product_id': product.id, 'lot_id': lot.id if lot else False, 'quantity': qty,
                'product_uom_id': product.uom_id.id, 'location_id': src.id, 'location_dest_id': dest.id,
                'company_id': self.env.company.id})],
        }
        if 'name' in Move._fields:
            vals['name'] = product.display_name
        move = Move.create(vals)
        move._action_confirm()
        move._action_done()
        return move

    def ka_location(self):
        """Emplacement interne portant actuellement le lot."""
        self.ensure_one()
        quant = self.env['stock.quant'].search([('lot_id', '=', self.id), ('quantity', '>', 0),
                                                ('location_id.usage', '=', 'internal')], limit=1)
        return quant.location_id

    def ka_liberer(self):
        """Libération : transfert de l'emplacement de contrôle vers le stock libre (statut A)."""
        controle = self.env.ref('kode_agri_production.loc_controle')
        libre = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1).lot_stock_id
        for lot in self:
            src = lot.ka_location()
            if src and src != libre:
                self.ka_move(lot.product_id, lot, lot.product_qty, src, libre)
            lot.ka_etat = 'A'

    def ka_reclasser(self, product, motif=''):
        """OF de reclassement « 1 pour 1 » (point structurant n° 3) : sortie de l'article initial et
        entrée du nouvel article sous le même numéro de lot. Retourne (nouveau lot, OF de reclassement)."""
        self.ensure_one()
        if product == self.product_id:
            return self, self.env['ka.of']
        src = self.ka_location() or self.env.ref('kode_agri_production.loc_controle')
        prod_loc = self.product_id.property_stock_production
        qty = self.product_qty or self.env['ka.of']._poids_colis()
        new_lot = self.copy({'name': self.name, 'product_id': product.id, 'ka_spec_id': self.ka_spec_id.id,
                             'ka_drc_histo_ids': False})
        self.ka_move(self.product_id, self, qty, src, prod_loc)
        self.ka_move(product, new_lot, qty, product.property_stock_production, src)
        of = self.env['ka.of'].create({
            'type': 'reclassement', 'product_id': product.id, 'qty': qty, 'state': 'solde',
            'tracabilite': self.ka_tracabilite, 'note': motif or _('Reclassement %s → %s') % (
                self.product_id.display_name, product.display_name)})
        return new_lot, of
