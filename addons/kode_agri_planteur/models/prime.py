from odoo import api, fields, models


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
        ('kg_achete', 'Par kg de FDT acheté'), ('forfait', 'Forfait ou selon volume du mois'),
        ('cumul', "Cumul de livraisons sur période"), ('qualite', "Critères qualité de la livraison"),
    ], string='Base de calcul', required=True, default='kg_achete')
    bareme = fields.Float(string='Barème (FCFA / kg humide)')
    periode = fields.Char(string="Période d'application", default='Campagne 2026')
    eligibilite = fields.Selection([('planteur_coop', 'Planteurs & coopératives')],
                                   string='Éligibilité', default='planteur_coop')
    imputation = fields.Char(string='Imputation', default='Coût de revient FDT', readonly=True)
    product_id = fields.Many2one('product.product', string='Élément de facture')
    active = fields.Boolean(default=True)
    state = fields.Selection([('brouillon', 'Brouillon'), ('actif', 'Active'), ('inactif', 'Inactive')],
                             default='actif', string='Statut')
    ka_titre = fields.Char(string='Titre', compute='_compute_ka_titre')

    def _ka_subtitle(self):
        self.ensure_one()
        return 'Acquise au planteur · ventilée sur %s' % (self.imputation or 'coût de revient FDT').replace(
            ' de revient', '').lower().replace('fdt', 'FDT')

    @api.depends('type_prime', 'periode', 'libelle')
    def _compute_ka_titre(self):
        types = dict(self._fields['type_prime'].selection)
        for rec in self:
            rec.ka_titre = ' — '.join(x for x in (types.get(rec.type_prime) or rec.libelle, rec.periode) if x)

    def action_activer(self):
        self.write({'state': 'actif', 'active': True})

    def action_desactiver(self):
        self.write({'state': 'inactif', 'active': False})
