from odoo import api, fields, models

from .common import TESTS, TESTS_PCT


class KaGrade(models.Model):
    _name = 'ka.grade'
    _description = 'Grade de caoutchouc'
    _order = 'sequence, id'

    name = fields.Char(string='Grade', required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one('product.product', string='Article produit')
    seuil_ids = fields.One2many('ka.grade.seuil', 'grade_id', string='Seuils de spécification')
    hors_specs = fields.Boolean(string='Grade de déclassement', help='Retenu quand aucun grade normé ne convient.')

    def verifie(self, valeurs):
        """Vrai si les résultats {test: valeur} respectent tous les seuils du grade."""
        self.ensure_one()
        return all(s.conforme(valeurs.get(s.test)) for s in self.seuil_ids)


class KaGradeSeuil(models.Model):
    _name = 'ka.grade.seuil'
    _description = 'Seuil de spécification'
    _order = 'grade_id, id'

    grade_id = fields.Many2one('ka.grade', required=True, ondelete='cascade')
    test = fields.Selection(TESTS, required=True)
    operateur = fields.Selection([('ge', '≥'), ('le', '≤'), ('client', 'Selon client')], default='ge', required=True)
    valeur = fields.Float(digits=(8, 2))
    texte = fields.Char(compute='_compute_texte')

    @api.depends('operateur', 'valeur')
    def _compute_texte(self):
        for s in self:
            if s.operateur == 'client':
                s.texte = 'Selon client'
            else:
                v = ('%.2f' % s.valeur).replace('.', ',') if s.test in TESTS_PCT else '%d' % s.valeur
                s.texte = '%s %s' % ('≥' if s.operateur == 'ge' else '≤', v)

    def conforme(self, valeur):
        self.ensure_one()
        if self.operateur == 'client':
            return True
        if valeur is None or valeur is False:
            return False
        return valeur >= self.valeur if self.operateur == 'ge' else valeur <= self.valeur
