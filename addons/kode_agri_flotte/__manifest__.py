{
    'name': 'Kode Agri — Module 11 : Gestion du parc automobile',
    'version': '19.0.1.0.0',
    'category': 'Kode Agri',
    'summary': "Véhicules et engins, entretien au kilométrage, carburant et dérives, documents réglementaires, "
               "affectations conducteurs et ordres de mission, prestations externes, coût de revient kilométrique",
    'depends': ['kode_agri_maintenance', 'kode_agri_vente'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/cron.xml',
        'views/vehicule_views.xml',
        'views/entretien_views.xml',
        'views/carburant_views.xml',
        'views/affectation_views.xml',
        'views/menus.xml',
    ],
    'license': 'LGPL-3',
    'application': True,
}
