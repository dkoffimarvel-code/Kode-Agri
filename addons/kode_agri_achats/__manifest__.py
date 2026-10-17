{
    'name': 'Kode Agri — Module 2 : Achats de frais généraux et stock',
    'version': '19.0.1.0.0',
    'category': 'Kode Agri',
    'summary': "Articles, catégories, fournisseurs, dépôts, demandes d'achat, appels d'offres, commandes, réceptions, factures, transferts, inventaires et dossiers d'import",
    'depends': ['kode_agri_production', 'purchase', 'stock', 'account', 'analytic'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/reference.xml',
        'views/master_views.xml',
        'views/achat_views.xml',
        'views/stock_views.xml',
        'views/dossier_views.xml',
        'views/menus.xml',
    ],
    'license': 'LGPL-3',
    'application': True,
}
