from odoo import fields, models


class KaDocument(models.AbstractModel):
    """Socle commun des documents Kode Agri : sous-titre affiché sous le titre de l'écran."""
    _name = 'ka.document'
    _description = 'Document Kode Agri'

    ka_subtitle = fields.Char(string='Sous-titre', compute='_compute_ka_subtitle')

    def _compute_ka_subtitle(self):
        for rec in self:
            rec.ka_subtitle = rec._ka_subtitle() or ''

    def _ka_subtitle(self):
        return self.display_name

    def action_creer(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'view_mode': 'form',
                'target': 'current'}

    def action_dupliquer(self):
        self.ensure_one()
        new = self.copy()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': new.id,
                'view_mode': 'form', 'target': 'current'}
