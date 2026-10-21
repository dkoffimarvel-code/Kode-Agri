{
    'name': 'Kode Agri — Module 10 : Maintenance des engins et des machines',
    'version': '19.0.1.0.0',
    'category': 'Kode Agri',
    'summary': "Parc d'équipements hiérarchisé, plans préventifs sur compteur ou calendrier, demandes d'intervention, "
               "ordres de travail (main-d'œuvre, pièces, sous-traitance), contrats de maintenance, MTBF / MTTR et coûts",
    'depends': ['kode_agri_rh', 'kode_agri_gestion', 'kode_agri_immo', 'kode_agri_production', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/reference.xml',
        'data/cron.xml',
        'views/equipement_views.xml',
        'views/plan_views.xml',
        'views/ot_views.xml',
        'views/demande_views.xml',
        'views/contrat_views.xml',
        'views/menus.xml',
    ],
    'license': 'LGPL-3',
    'application': True,
}
