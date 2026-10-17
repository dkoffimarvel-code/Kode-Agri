from odoo import api, fields, models


class KaGestionParam(models.Model):
    """Objectifs et seuils des indicateurs de pilotage (« Paramétrer les indicateurs », § 8.3, 8.5.3)."""
    _name = 'ka.gestion.param'
    _description = 'Paramètres des indicateurs de gestion'

    name = fields.Char(default='Paramètres des indicateurs')
    cible_fob = fields.Float(string='Objectif coût de revient FOB (F/kg)', default=800)
    cible_rendement = fields.Float(string='Rendement cible (%)', default=78)
    seuil_ecart = fields.Float(string='Seuil d\'alerte écart budgétaire (%)', default=2.0)
    seuil_tresorerie = fields.Float(string='Seuil de sécurité de trésorerie (FCFA)', default=150_000_000)
    standard_usinage = fields.Float(string="Coût standard d'usinage (F/kg)", default=145)
    campagne = fields.Integer(string='Campagne', default=lambda s: fields.Date.today().year)

    @api.model
    def get(self):
        rec = self.search([], limit=1)
        return rec or self.create({})
