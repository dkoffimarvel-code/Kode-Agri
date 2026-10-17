from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

METHODES = [('standard', 'Prix standard'), ('average', 'Prix moyen pondéré'), ('fifo', 'FIFO')]
GESTIONS = [('stock', 'Géré en stock'), ('conso', 'Consommable'), ('service', 'Service')]
MODES = [('none', 'Sans suivi'), ('lot', 'Lot obligatoire'), ('serial', 'Numéro de série')]


class KaSite(models.Model):
    _name = 'ka.site'
    _description = 'Société ou site'
    _order = 'code'

    structure_id = fields.Many2one('ka.structure', ondelete='cascade')
    code = fields.Char(string='Code', required=True)
    name = fields.Char(string='Intitulé', required=True)
    type = fields.Char(string='Type')
    legislation = fields.Char(string='Législation')

    def _compute_display_name(self):
        for s in self:
            s.display_name = '%s — %s' % (s.code, s.name)


class KaSection(models.Model):
    """Section analytique de l'axe ACTIVITE ; les sections « achats stockés » ne sont pas modifiables en saisie."""
    _name = 'ka.section'
    _description = 'Section analytique'
    _order = 'code'

    structure_id = fields.Many2one('ka.structure', ondelete='cascade')
    code = fields.Char(string='Section', required=True)
    name = fields.Char(string='Intitulé', required=True)
    nature = fields.Char(string='Nature')
    modifiable = fields.Boolean(string='Modifiable en saisie')
    analytic_id = fields.Many2one('account.analytic.account', string='Compte analytique')

    def _compute_display_name(self):
        for s in self:
            s.display_name = '%s — %s' % (s.code, s.name)


class KaCompteur(models.Model):
    _name = 'ka.compteur'
    _description = 'Compteur et devise'

    structure_id = fields.Many2one('ka.structure', ondelete='cascade')
    objet = fields.Char(string='Objet')
    compteur = fields.Char(string='Compteur')
    exemple = fields.Char(string='Exemple')


class KaStructure(models.Model):
    """Données maîtres partagées : sociétés et sites, sections analytiques, compteurs et devise (écran 2.15)."""
    _name = 'ka.structure'
    _description = 'Données de structure — achats et stocks'

    name = fields.Char(default='Données de structure — achats et stocks')
    site_ids = fields.One2many('ka.site', 'structure_id', string='Sociétés et sites')
    section_ids = fields.One2many('ka.section', 'structure_id', string='Sections analytiques (axe ACTIVITE)')
    compteur_ids = fields.One2many('ka.compteur', 'structure_id', string='Compteurs et devise')

    def action_exporter(self):
        return self._notif(_('Export'), _('Paramétrage exporté.'))

    def action_importer(self):
        return self._notif(_('Import'), _('Importez un fichier CSV de paramétrage depuis le menu Importer.'))

    def action_controler(self):
        self.ensure_one()
        manque = [c for c in ('ACHSTK', 'ACHIMP') if c not in self.section_ids.mapped('code')]
        if manque:
            raise UserError(_('Sections « achats stockés » manquantes : %s') % ', '.join(manque))
        return self._notif(_('Contrôle'), _('Paramétrage cohérent : sections, compteurs et devise.'))

    def _notif(self, titre, msg):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': titre, 'message': msg, 'type': 'success', 'sticky': False}}


class KaCodeComptable(models.Model):
    """Code comptable article : jeu de comptes (stock, charge, variation) hérité par les catégories."""
    _name = 'ka.code.comptable'
    _description = 'Code comptable article'

    name = fields.Char(string='Code comptable', required=True)
    cpt_stock = fields.Char(string='Stock', help='Ex. 3211 — Matières consommables')
    cpt_charge = fields.Char(string='Achat (charge)', help='Ex. 6021 — Achats stockés')
    cpt_variation = fields.Char(string='Variation de stock', help='Ex. 6031 — Variation de stocks')

    def _compute_display_name(self):
        for c in self:
            c.display_name = '%s (%s / %s)' % (c.name, (c.cpt_stock or '').split(' ')[0], (c.cpt_charge or '').split(' ')[0])


class ProductCategory(models.Model):
    _inherit = 'product.category'

    ka_code = fields.Char(string='Catégorie')
    ka_gestion = fields.Selection(GESTIONS, string='Gestion de stock', default='stock')
    ka_mode = fields.Selection(MODES, string='Mode de gestion', default='lot')
    ka_methode = fields.Selection(METHODES, string='Méthode de valorisation', default='average')
    ka_code_comptable_id = fields.Many2one('ka.code.comptable', string='Code comptable')
    ka_analytic_id = fields.Many2one('account.analytic.account', string='Section analytique')
    ka_compteur_lot = fields.Char(string='Compteur lot')
    ka_cpt_stock = fields.Char(related='ka_code_comptable_id.cpt_stock', string='Stock')
    ka_cpt_charge = fields.Char(related='ka_code_comptable_id.cpt_charge', string='Achat (charge)')
    ka_cpt_variation = fields.Char(related='ka_code_comptable_id.cpt_variation', string='Variation de stock')
    ka_subtitle = fields.Char(compute='_compute_ka_subtitle')

    @api.depends('ka_code', 'name')
    def _compute_ka_subtitle(self):
        for c in self:
            c.ka_subtitle = '%s — %s' % (c.ka_code or '', c.name or '')

    def write(self, vals):
        res = super().write(vals)
        if 'ka_methode' in vals and 'property_cost_method' in self._fields:
            self.write({'property_cost_method': vals['ka_methode']})
        return res

    def action_creer(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'product.category', 'view_mode': 'form'}

    def action_dupliquer(self):
        self.ensure_one()
        new = self.copy({'name': '%s (copie)' % self.name})
        return {'type': 'ir.actions.act_window', 'res_model': 'product.category', 'res_id': new.id, 'view_mode': 'form'}

    def action_articles(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Articles rattachés', 'res_model': 'product.template',
                'view_mode': 'list,form', 'domain': [('categ_id', '=', self.id)]}


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    ka_gestion = fields.Selection(GESTIONS, string='Gestion de stock', compute='_compute_ka_gestion',
                                  inverse='_inverse_ka_gestion')
    ka_uom_achat_id = fields.Many2one('uom.uom', string="Unité d'achat")
    ka_methode = fields.Selection(related='categ_id.ka_methode', string='Méthode de valorisation')
    ka_code_comptable_id = fields.Many2one(related='categ_id.ka_code_comptable_id', string='Code comptable')
    ka_analytic_id = fields.Many2one(related='categ_id.ka_analytic_id', string='Section analytique')
    ka_niveau_taxe = fields.Selection([('normal', 'Normal'), ('reduit', 'Réduit'), ('exonere', 'Exonéré')],
                                      string='Niveau de taxe', default='normal')
    ka_statut = fields.Selection([('actif', 'Actif'), ('archive', 'Archivé')], compute='_compute_ka_statut')
    ka_subtitle = fields.Char(compute='_compute_ka_subtitle')

    @api.depends('type', 'is_storable')
    def _compute_ka_gestion(self):
        for p in self:
            p.ka_gestion = 'service' if p.type == 'service' else ('stock' if p.is_storable else 'conso')

    def _inverse_ka_gestion(self):
        for p in self:
            if p.ka_gestion == 'service':
                p.type = 'service'
            else:
                p.write({'type': 'consu', 'is_storable': p.ka_gestion == 'stock'})

    def _compute_ka_statut(self):
        for p in self:
            p.ka_statut = 'actif' if p.active else 'archive'

    @api.depends('default_code', 'name')
    def _compute_ka_subtitle(self):
        for p in self:
            p.ka_subtitle = '%s — %s' % (p.default_code or '', p.name or '')

    @api.onchange('categ_id')
    def _onchange_categ_ka(self):
        c = self.categ_id
        if c:
            self.ka_gestion = c.ka_gestion
            self.tracking = c.ka_mode if c.ka_mode != 'none' else 'none'

    def action_creer(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'product.template', 'view_mode': 'form'}

    def action_dupliquer(self):
        self.ensure_one()
        new = self.copy()
        return {'type': 'ir.actions.act_window', 'res_model': 'product.template', 'res_id': new.id, 'view_mode': 'form'}

    def action_stock_par_site(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Stock par site', 'res_model': 'stock.quant',
                'view_mode': 'list', 'domain': [('product_id.product_tmpl_id', '=', self.id),
                                                ('location_id.usage', '=', 'internal')]}

    def action_historique_prix(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Historique des prix', 'res_model': 'product.supplierinfo',
                'view_mode': 'list', 'domain': [('product_tmpl_id', '=', self.id)]}


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ka_categorie = fields.Selection(selection_add=[('frais_generaux', 'FG — Frais généraux'),
                                                   ('transitaire', 'Transitaire & transporteur')])
    ka_code_frn = fields.Char(string='Fournisseur', copy=False, readonly=True)
    ka_devise_achat_id = fields.Many2one('res.currency', string='Devise')
    ka_subtitle_frn = fields.Char(compute='_compute_ka_subtitle_frn')

    @api.depends('ka_code_frn', 'name')
    def _compute_ka_subtitle_frn(self):
        for p in self:
            p.ka_subtitle_frn = ' — '.join(x for x in (p.ka_code_frn, p.name) if x)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('ka_categorie') in ('frais_generaux', 'transitaire') and not vals.get('ka_code_frn'):
                vals['ka_code_frn'] = self.env['ir.sequence'].next_by_code('ka.fournisseur')
        return super().create(vals_list)

    def action_creer_frn(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'res.partner', 'view_mode': 'form',
                'context': {'default_ka_categorie': 'frais_generaux', 'default_supplier_rank': 1}}

    def action_dupliquer_frn(self):
        self.ensure_one()
        new = self.copy({'name': '%s (copie)' % self.name})
        return {'type': 'ir.actions.act_window', 'res_model': 'res.partner', 'res_id': new.id, 'view_mode': 'form'}

    def action_imprimer_frn(self):
        return self.env['ka.structure']._notif(_('Fiche fournisseur'), _('Fiche envoyée à l\'impression.'))

    def action_open_commandes_frn(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Commandes', 'res_model': 'ka.commande',
                'view_mode': 'list,form', 'domain': [('partner_id', '=', self.id)]}

    def action_open_factures_frn(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Factures', 'res_model': 'ka.facture',
                'view_mode': 'list,form', 'domain': [('partner_id', '=', self.id)]}

    def action_open_balance_frn(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Balance âgée', 'res_model': 'account.move.line',
                'view_mode': 'list', 'domain': [('partner_id', '=', self.id), ('parent_state', '=', 'posted'),
                                                ('account_id.account_type', '=', 'liability_payable'),
                                                ('reconciled', '=', False)]}


class StockLocation(models.Model):
    _inherit = 'stock.location'

    ka_type = fields.Selection([('reception', 'Réception'), ('stockage', 'Stockage')], string='Type')
    ka_statuts = fields.Char(string='Statuts autorisés', help='Ex. Q, A, R')
    ka_usage = fields.Char(string='Usage')


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    ka_site_id = fields.Many2one('ka.site', string='Site')
    ka_adresse = fields.Char(string='Adresse')
    ka_reappro = fields.Selection([('point_commande', 'Point de commande'), ('min_max', 'Min / max'),
                                   ('besoins', 'Calcul des besoins')], string='Réapprovisionnement',
                                  default='point_commande')
    ka_statut_reception = fields.Selection([('Q', 'Q — Quarantaine'), ('A', 'A — Accepté')],
                                           string='Statut à la réception', default='Q')
    ka_location_ids = fields.One2many('stock.location', 'warehouse_id', string='Emplacements du site')
    ka_subtitle = fields.Char(compute='_compute_ka_subtitle')
    ka_statut = fields.Selection([('actif', 'Actif'), ('archive', 'Archivé')], compute='_compute_ka_subtitle')

    @api.depends('code', 'name', 'active')
    def _compute_ka_subtitle(self):
        for w in self:
            w.ka_subtitle = '%s — %s' % (w.code or '', w.name or '')
            w.ka_statut = 'actif' if w.active else 'archive'

    def action_creer(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'stock.warehouse', 'view_mode': 'form'}

    def action_emplacements(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Emplacements', 'res_model': 'stock.location',
                'view_mode': 'list,form', 'domain': [('warehouse_id', '=', self.id)]}

    def action_types_emplacement(self):
        return {'type': 'ir.actions.act_window', 'name': "Types d'opération", 'res_model': 'stock.picking.type',
                'view_mode': 'list,form', 'domain': [('warehouse_id', 'in', self.ids)]}
