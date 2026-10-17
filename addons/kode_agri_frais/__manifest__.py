{
    'name': 'Kode Agri — Module 6 : Notes de frais',
    'version': '19.0.1.0.0',
    'category': 'Kode Agri',
    'summary': "Saisie, approbation, comptabilisation et remboursement des notes de frais, avec plafonds par catégorie",
    'depends': ['kode_agri_planteur', 'account', 'analytic'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/reference.xml',
        'views/note_views.xml',
        'views/reglement_views.xml',
        'views/menus.xml',
    ],
    'license': 'LGPL-3',
    'application': True,
}
