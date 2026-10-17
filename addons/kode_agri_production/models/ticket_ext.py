from odoo import api, fields, models


class KaTicket(models.Model):
    _inherit = 'ka.ticket'

    ka_poids1 = fields.Float(string='Poids 1', digits=(8, 0))
    ka_poids2 = fields.Float(string='Poids 2', digits=(8, 0))
    ka_transport = fields.Char(string='Transport')
    ka_qc_ids = fields.One2many('ka.qc.reception', 'ticket_id', string='Contrôles réception')

    @api.model_create_multi
    def create(self, vals_list):
        tickets = super().create(vals_list)
        # § 4.3.1 : un contrôle de réception est généré automatiquement sur chaque ticket de pesée.
        self.env['ka.qc.reception'].create([
            {'ticket_id': t.id, 'tracabilite': 'eudr'} for t in tickets])
        return tickets
