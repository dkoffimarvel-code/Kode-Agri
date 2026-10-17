{
    'name': 'Kode Agri — Module 8 : Contrôle de gestion',
    'version': '19.0.1.0.0',
    'category': 'Kode Agri',
    'summary': "Cascade analytique, unités d'œuvre et clés, budgets à deux couches, CAPEX, écarts, KPI, P&L de gestion, trésorerie glissante",
    'depends': ['kode_agri_compta', 'purchase', 'account', 'analytic'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/reference.xml',
        'views/analytique_views.xml',
        'views/budget_views.xml',
        'views/bab_views.xml',
        'views/pilotage_views.xml',
        'views/menus.xml',
    ],
    'license': 'LGPL-3',
    'application': True,
}
