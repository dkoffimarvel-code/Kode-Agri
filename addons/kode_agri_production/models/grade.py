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
    operateur = fields.Selection([('ge', '≥'), ('le', '≤'), ('between', 'Entre'), ('client', 'Selon client')],
                                 default='ge', required=True)
    valeur = fields.Float(digits=(8, 2))
    valeur2 = fields.Float(string='Borne haute', digits=(8, 2))
    texte = fields.Char(compute='_compute_texte')

    @api.depends('operateur', 'valeur', 'valeur2')
    def _compute_texte(self):
        for s in self:
            if s.operateur == 'client':
                s.texte = 'Selon client'
            else:
                def fmt(x):
                    return ('%.2f' % x).replace('.', ',') if s.test in TESTS_PCT else '%d' % x
                if s.operateur == 'between':
                    s.texte = '%s – %s' % (fmt(s.valeur), fmt(s.valeur2))
                else:
                    s.texte = '%s %s' % ('≥' if s.operateur == 'ge' else '≤', fmt(s.valeur))

    def conforme(self, valeur):
        self.ensure_one()
        if self.operateur == 'client':
            return True
        if valeur is None or valeur is False:
            return False
        if self.operateur == 'between':
            return self.valeur <= valeur <= self.valeur2
        return valeur >= self.valeur if self.operateur == 'ge' else valeur <= self.valeur
