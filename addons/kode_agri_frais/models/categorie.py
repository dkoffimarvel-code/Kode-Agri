from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ka_salarie = fields.Boolean(string='Salarié')
    ka_matricule = fields.Char(string='Matricule', help='Ex. EMP-0142')


class KaFraisCategorie(models.Model):
    """Catégorie de dépenses rattachée à un compte de charge, avec plafond (§ 6.2)."""
    _name = 'ka.frais.categorie'
    _description = 'Catégorie de frais'
    _order = 'code'

    code = fields.Char(string='Code frais', required=True)
    name = fields.Char(string='Libellé', required=True)
    compte_code = fields.Char(string='Compte de charge', required=True, help='Ex. 605100')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    plafond = fields.Monetary(string='Plafond par dépense', help='0 = pas de plafond')

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for c in self:
            c.display_name = '%s — %s' % (c.code, c.name)
