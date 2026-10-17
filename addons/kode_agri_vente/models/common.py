import re

from odoo.addons.kode_agri_production.models.common import POIDS_COLIS, ka_param  # noqa: F401

TESTS_SPEC = [('p0', 'P0'), ('pri', 'PRI'), ('ml', 'ML'), ('vm', 'VM'), ('azote', 'Azote'),
              ('cendres', 'Cendres'), ('imp', 'Imp.')]
LIBELLES = {'p0': 'Plasticité Wallace initiale', 'pri': 'Indice de rétention', 'ml': 'Viscosité Mooney',
            'vm': 'Matières volatiles', 'azote': 'Azote', 'cendres': 'Taux de cendres', 'imp': "Taux d'impuretés"}
# Grille standard par grade (§ 5.2.2, RG-5.10)
GRILLE = {
    'TSR10': {'p0': '≥ 30', 'pri': '≥ 50', 'ml': 'Selon client', 'imp': '≤ 0,10', 'vm': '≤ 0,80',
              'azote': '≤ 0,60', 'cendres': '≤ 0,75'},
    'TSR20': {'p0': '≥ 30', 'pri': '40 – 49', 'ml': 'NAP', 'imp': '≤ 0,20', 'vm': '0,90 – 1',
              'azote': '0,70 – 0,90', 'cendres': '≥ 1'},
    'OFFSPECS': {'p0': '≤ 30', 'pri': '≤ 40', 'ml': 'NAP', 'imp': 'NAP', 'vm': '≥ 1',
                 'azote': '≥ 1', 'cendres': '≥ 1'},
}
ARMATEURS = [('MAERSK', 'MAERSK'), ('CMA CGM', 'CMA CGM'), ('MSC', 'MSC')]
DETENTION_JOURS = {'MAERSK': 13, 'CMA CGM': 30, 'MSC': 30}   # RG-5.8
ARMATEURS_BMC = ('MAERSK',)                                  # RG-5.7
EMBALLAGES = [('gps5', 'Metal box GPS5'), ('mb5', 'Metal box MB5'), ('palette', 'Palette en plastique'),
              ('vrac', 'En vrac')]
PAIEMENTS = [('prefinancement', 'Préfinancement'), ('remise_doc', 'Remise documentaire')]
TAUX_CHANGE_EUR_XOF = 655.957


def num(txt):
    return float(txt.replace(',', '.').replace(' ', ''))


def spec_ok(applique, standard, valeur):
    """Teste une valeur de laboratoire contre une exigence (« ≥ 30 », « 40 – 49 », « 0,90 »...).
    Un nombre seul prend le sens de la grille standard de la même ligne."""
    txt = (applique or '').strip()
    if not txt or txt.upper() == 'NAP' or txt.lower().startswith('selon'):
        return True
    if valeur is None:
        return False
    m = re.match(r'^([≥≤])\s*([\d.,]+)$', txt)
    if m:
        v = num(m.group(2))
        return valeur >= v if m.group(1) == '≥' else valeur <= v
    m = re.match(r'^([\d.,]+)\s*[–-]\s*([\d.,]+)$', txt)
    if m:
        return num(m.group(1)) <= valeur <= num(m.group(2))
    try:
        v = num(txt)
    except ValueError:
        return True
    return valeur >= v if (standard or '').startswith('≥') else valeur <= v
