{
    'name': 'Kode Agri — Module 3 : Immobilisations',
    'version': '19.0.1.0.0',
    'category': 'Kode Agri',
    'summary': "Familles, immobilisations (manuelles ou issues d'une facture), plans d'amortissement, dotations, sorties",
    'depends': ['kode_agri_achats', 'account', 'analytic'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/reference.xml',
        'views/immo_views.xml',
        'views/famille_views.xml',
        'views/parc_views.xml',
        'views/dotation_views.xml',
        'views/menus.xml',
    ],
    'license': 'LGPL-3',
    'application': True,
}
