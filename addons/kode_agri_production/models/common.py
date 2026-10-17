from odoo import _, fields, models

TRACABILITE = [('eudr', 'EUDR'), ('non_eudr', 'NON EUDR')]
TESTS = [('p0', 'P0 (plasticité initiale)'), ('pri', 'PRI'), ('ml', 'Viscosité Mooney (ML)'),
         ('imp', 'Impuretés'), ('azote', 'Azote'), ('cendres', 'Cendres'), ('vm', 'Matières volatiles')]
TESTS_PCT = ('imp', 'azote', 'cendres', 'vm')
TEXTURES = [('conforme', 'Conforme'), ('points_blancs', 'Points blancs'), ('contamine', 'Contaminé'),
            ('humide', 'Humide'), ('autre', 'Autre')]
POIDS_BALLE = 35.0
BALLES_COLIS = 36
POIDS_COLIS = POIDS_BALLE * BALLES_COLIS  # 1 260 kg


def ka_param(env, key, default):
    """Paramètre système Kode Agri (ex. DRC de référence)."""
    value = env['ir.config_parameter'].sudo().get_param('kode_agri.%s' % key)
    try:
        return float(value) if value not in (None, False, '') else default
    except ValueError:
        return default


class KaTracabilite(models.AbstractModel):
    """Aide : statut de traçabilité EUDR = ET logique des origines (RG-1.12)."""
    _name = 'ka.tracabilite.mixin'
    _description = 'Statut de traçabilité'

    tracabilite = fields.Selection(TRACABILITE, string='Statut de traçabilité', default='eudr')
