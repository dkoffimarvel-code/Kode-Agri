from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    ka_piece_mnt = fields.Boolean(string='Pièce de maintenance', help='Pièce détachée ou consommable du magasin pièces')
    ka_piece_critique = fields.Boolean(string='Pièce critique')
    ka_stock_mini = fields.Float(string='Stock d\'alerte', digits=(10, 2))
    ka_alerte_reappro = fields.Boolean(compute='_compute_ka_alerte', search='_search_ka_alerte',
                                       string='Alerte de réapprovisionnement')

    @api.depends('ka_stock_mini')
    def _compute_ka_alerte(self):
        for t in self:
            t.ka_alerte_reappro = t.ka_piece_mnt and t.qty_available <= t.ka_stock_mini

    def _search_ka_alerte(self, operator, value):
        # Odoo 19 normalise les conditions booléennes en ('in', [True]) / ('not in', [True])
        if operator not in ('in', 'not in'):
            return NotImplemented
        ids = self.search([('ka_piece_mnt', '=', True)]).filtered(lambda t: t.qty_available <= t.ka_stock_mini).ids
        return [('id', operator, ids)]
