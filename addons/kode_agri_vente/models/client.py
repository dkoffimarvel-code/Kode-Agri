from odoo import _, api, fields, models

from .common import LIBELLES, PAIEMENTS


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ka_client = fields.Boolean(string='Client Kode Agri')
    ka_code_client = fields.Char(string='Client', copy=False, readonly=True)
    ka_cat_client = fields.Selection([('export', 'EXPORT — Clients export'), ('local', 'LOCAL — Clients locaux')],
                                     string='Catégorie client', default='export')
    ka_contact_commercial = fields.Char(string='Contact commercial')
    ka_acces_ventes = fields.Char(string="Code d'accès", default='VENTES')
    ka_devise_id = fields.Many2one('res.currency', string='Devise',
                                   default=lambda s: s.env.ref('base.EUR', raise_if_not_found=False))
    ka_incoterm = fields.Char(string='Incoterm', default='FOB Abidjan')
    ka_paiement = fields.Selection(PAIEMENTS, string='Condition de paiement', default='remise_doc')
    ka_banque = fields.Char(string='Banque de domiciliation')
    ka_collectif = fields.Char(string='Collectif', default='4111 — Clients export')
    ka_regime_taxe = fields.Char(string='Régime de taxe', default='Exonéré — export')
    ka_delai_reglement = fields.Integer(string='Délai de règlement', default=7)
    ka_encours_id = fields.Many2one('res.currency', default=lambda s: s.env.ref('base.USD', raise_if_not_found=False))
    ka_encours = fields.Monetary(string='Encours autorisé', currency_field='ka_encours_id')
    ka_spec_ids = fields.One2many('ka.client.spec', 'partner_id', string='Spécifications qualité par défaut')
    ka_doc_analyse = fields.Boolean(string="certificat d'analyse qualité", default=True)
    ka_doc_thermique = fields.Boolean(string='certificat de traitement thermique', default=True)
    ka_doc_phyto = fields.Boolean(string='certificat phytosanitaire', default=True)
    ka_doc_garantie = fields.Boolean(string='certificat de garantie')
    ka_doc_colisage = fields.Boolean(string='liste de colisage', default=True)
    ka_doc_bl = fields.Boolean(string='connaissement (BL)', default=True)
    ka_doc_daex = fields.Boolean(string="déclaration d'exportation (DAEX)", default=True)
    ka_client_state = fields.Selection([('creation', 'En création'), ('actif', 'Actif')], default='creation',
                                       string='Statut client')
    ka_subtitle_client = fields.Char(compute='_compute_ka_subtitle_client')

    @api.depends('name', 'ka_client_state')
    def _compute_ka_subtitle_client(self):
        for p in self:
            p.ka_subtitle_client = ('Nouveau client — %s' if p.ka_client_state == 'creation' else 'Client — %s') % (
                p.name or '')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('ka_client') and not vals.get('ka_code_client'):
                vals['ka_code_client'] = self.env['ir.sequence'].next_by_code('ka.client')
        return super().create(vals_list)

    def action_creer_client(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'res.partner', 'view_mode': 'form',
                'context': {'default_ka_client': True, 'default_customer_rank': 1}}

    def action_activer_client(self):
        self.write({'ka_client_state': 'actif'})

    def action_annuler_client(self):
        self.write({'active': False})


class KaClientSpec(models.Model):
    _name = 'ka.client.spec'
    _description = 'Spécification qualité par défaut du client'
    _order = 'id'

    partner_id = fields.Many2one('res.partner', required=True, ondelete='cascade')
    test = fields.Selection([('p0', 'P0'), ('pri', 'PRI'), ('ml', 'ML'), ('vm', 'VM'), ('azote', 'N'),
                             ('cendres', 'Cendres'), ('imp', 'Impuretés')], required=True, string='Test')
    libelle = fields.Char(compute='_compute_libelle', string='Libellé')
    vmin = fields.Char(string='Min')
    vmax = fields.Char(string='Max')
    texte = fields.Char(compute='_compute_texte')

    @api.depends('test')
    def _compute_libelle(self):
        lib = dict(LIBELLES, azote='Teneur en azote', pri='Plasticity Retention Index')
        for s in self:
            s.libelle = lib.get(s.test, '')

    @api.depends('vmin', 'vmax')
    def _compute_texte(self):
        for s in self:
            if s.vmin and s.vmax:
                s.texte = '%s – %s' % (s.vmin, s.vmax)
            elif s.vmin:
                s.texte = '≥ %s' % s.vmin
            elif s.vmax:
                s.texte = '≤ %s' % s.vmax
            else:
                s.texte = ''
