from odoo import fields, models


class KaPrimeType(models.Model):
    _name = 'ka.prime.type'
    _description = 'Paramétrage des primes'
    _inherit = ['ka.document']

    name = fields.Char(string='Code', required=True)
    libelle = fields.Char(string='Libellé')
    type_prime = fields.Selection([
        ('kg', 'Prime au kilogramme'), ('mensuelle', 'Prime mensuelle'),
        ('fidelite', 'Prime de fidélité / volume'), ('qualite', 'Prime de qualité'),
    ], string='Type de prime', required=True, default='kg')
    base_calcul = fields.Selection([
        ('kg_achete', 'Par kg de fond de tasse acheté'), ('forfait', 'Forfait ou selon le volume du mois'),
        ('cumul', "Cumul d'apports sur la période"), ('qualite', "Critères qualité de l'apport"),
    ], string='Base de calcul', required=True, default='kg_achete')
    bareme = fields.Float(string='Barème (FCFA / kg humide)')
    periode = fields.Char(string="Période d'application", default='Campagne 2026')
    eligibilite = fields.Selection([('planteur_coop', 'Catégorie Planteur & coopérative')],
                                   string='Éligibilité', default='planteur_coop')
    imputation = fields.Char(string='Imputation', default='Coût de revient FDT', readonly=True)
    product_id = fields.Many2one('product.product', string='Élément de facture')
    active = fields.Boolean(default=True)
    state = fields.Selection([('actif', 'Actif'), ('inactif', 'Inactif')], default='actif', string='Statut')

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — %s, %s' % (self.name or '', dict(self._fields['type_prime'].selection).get(
            self.type_prime, ''), (self.periode or '').lower())

    def action_desactiver(self):
        self.write({'state': 'inactif', 'active': False})
