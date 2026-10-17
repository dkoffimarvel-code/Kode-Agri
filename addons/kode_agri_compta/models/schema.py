from odoo import fields, models


class KaSchema(models.Model):
    """Schéma d'écritures automatiques du cahier (cahier de paramétrage des comptes, journaux et catégories)."""
    _name = 'ka.schema'
    _description = "Schéma d'écriture comptable"
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    domaine = fields.Selection([
        ('achats', 'Achats et fournisseurs'), ('ventes', 'Ventes et clients'), ('immo', 'Immobilisations'),
        ('personnel', 'Notes de frais'), ('arrete', "Régularisations d'arrêté et provisions")], string='Domaine', required=True)
    rubrique = fields.Char(string='Rubrique', required=True)
    operation = fields.Char(string='Opération', required=True)
    debit = fields.Char(string='Débit')
    credit = fields.Char(string='Crédit')
    regle = fields.Char(string='Règle de gestion')
