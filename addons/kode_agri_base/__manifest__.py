{
    'name': 'Kode Agri — Socle et habillage',
    'version': '17.0.1.0.0',
    'category': 'Kode Agri',
    'summary': "Habillage Kode Agri (barre noire, panneau Actions/Liens, pastilles, bandeaux) et devise FCFA",
    'depends': ['base', 'web', 'mail'],
    'data': ['data/currency.xml'],
    'assets': {
        'web.assets_backend': [
            'kode_agri_base/static/src/css/kode_agri.css',
            'kode_agri_base/static/src/js/navbar.js',
            'kode_agri_base/static/src/xml/navbar.xml',
        ],
    },
    'license': 'LGPL-3',
    'application': False,
}
