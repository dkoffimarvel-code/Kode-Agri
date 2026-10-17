from odoo import api, fields, models


class MrpRoutingWorkcenter(models.Model):
    """Gamme : temps opératoire (h) et cadence (/h) calculés à partir de la durée de l'opération (§ 4.1)."""
    _inherit = 'mrp.routing.workcenter'

    ka_temps_h = fields.Float(string='Temps opératoire (h)', compute='_compute_ka_cadence', digits=(6, 3))
    ka_cadence = fields.Float(string='Cadence (/h)', compute='_compute_ka_cadence', digits=(8, 1))
    ka_centre = fields.Selection(related='workcenter_id.ka_centre', string='Centre de charge')
    ka_code_poste = fields.Char(related='workcenter_id.code', string='Poste de charge')

    @api.depends('time_cycle_manual')
    def _compute_ka_cadence(self):
        for op in self:
            op.ka_temps_h = (op.time_cycle_manual or 0.0) / 60.0
            op.ka_cadence = (1.0 / op.ka_temps_h) if op.ka_temps_h else 0.0


class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    ka_centre = fields.Selection([('CC01', 'CC01 — Prélavage'), ('CC02', 'CC02 — Zone humide'),
                                  ('CC03', 'CC03 — Zone sèche'), ('CC04', 'CC04 — Mise en moule')],
                                 string='Centre de charge')


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    ka_gamme = fields.Char(string='Gamme', default='GAM-TSR-01')
    ka_etat = fields.Selection([('brouillon', 'Brouillon'), ('validee', 'Validée')], string='Statut',
                               default='validee')
    ka_subtitle = fields.Char(compute='_compute_ka_subtitle')

    def _compute_ka_subtitle(self):
        for b in self:
            b.ka_subtitle = '%s — article en attente de spécifications · nomenclature de production' % (
                b.product_tmpl_id.default_code or b.product_tmpl_id.name or '')

    def action_copier(self):
        self.ensure_one()
        new = self.copy()
        return {'type': 'ir.actions.act_window', 'res_model': 'mrp.bom', 'res_id': new.id, 'view_mode': 'form'}

    def action_cout_standard(self):
        """Coût standard opératoire = Σ temps (h) × coût horaire du poste (§ 4.1)."""
        self.ensure_one()
        cout = sum(op.ka_temps_h * op.workcenter_id.costs_hour for op in self.operation_ids)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'Coût standard', 'type': 'success', 'sticky': False,
                           'message': 'Coût opératoire standard : %.0f par unité de base.' % cout}}
