from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ka_categorie = fields.Selection([
        ('planteur_coop', 'Planteur & coopérative'),
        ('autre', 'Autre fournisseur'),
    ], string='Catégorie fournisseur')
    ka_code = fields.Char(string='Code planteur', copy=False, readonly=True)
    ka_code_acces = fields.Char(string="Code d'accès", default='COLLECTE')
    ka_cooperative_id = fields.Many2one('res.partner', string='Coopérative de rattachement',
                                        domain=[('ka_categorie', '=', 'planteur_coop')])
    ka_mode_reglement = fields.Selection([
        ('vir', 'Virement bancaire'), ('chq', 'Chèque'), ('caisse', 'Caisse'), ('mobile', 'Mobile money'),
    ], string='Mode de règlement')
    ka_bareme_id = fields.Many2one('ka.tarif.bareme', string='Prix Apromac')
    ka_parcelle_ids = fields.One2many('ka.parcelle', 'partner_id', string="Parcelles d'origine (EUDR)")
    ka_nb_apports = fields.Integer(string='Livraisons de la campagne', compute='_compute_ka_stats')
    ka_solde_avance = fields.Monetary(string="Solde d'avance", compute='_compute_ka_stats',
                                      currency_field='ka_currency_id')
    ka_currency_id = fields.Many2one('res.currency', compute='_compute_ka_currency')
    ka_subtitle = fields.Char(compute='_compute_ka_subtitle')
    ka_statut = fields.Selection([('actif', 'Actif'), ('archive', 'Archivé')], compute='_compute_ka_statut')
    ka_avance_ids = fields.One2many('ka.avance', 'partner_id', string='Avances')
    ka_ticket_ids = fields.One2many('ka.ticket', 'partner_id', string='Tickets de pesée')

    @api.depends('ka_code', 'name')
    def _compute_ka_subtitle(self):
        for rec in self:
            rec.ka_subtitle = ' — '.join(x for x in (rec.ka_code, rec.name) if x)

    def action_creer_partner(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'res.partner', 'view_mode': 'form',
                'context': {'default_ka_categorie': 'planteur_coop', 'default_supplier_rank': 1}}

    def _compute_ka_statut(self):
        for rec in self:
            rec.ka_statut = 'actif' if rec.active else 'archive'

    def _compute_ka_currency(self):
        for rec in self:
            rec.ka_currency_id = rec.company_id.currency_id or self.env.company.currency_id

    @api.depends('ka_avance_ids.state', 'ka_avance_ids.amount', 'ka_avance_ids.recupere',
                 'ka_ticket_ids.state')
    def _compute_ka_stats(self):
        for rec in self:
            rec.ka_nb_apports = len(rec.ka_ticket_ids.filtered(lambda t: t.state == 'valide'))
            versees = rec.ka_avance_ids.filtered(lambda a: a.state in ('versee', 'recuperee'))
            rec.ka_solde_avance = sum(versees.mapped('amount')) - sum(versees.mapped('recupere'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('ka_categorie') == 'planteur_coop' and not vals.get('ka_code'):
                coop = vals.get('is_company')
                seq = 'ka.coop' if coop else 'ka.planteur'
                vals['ka_code'] = self.env['ir.sequence'].next_by_code(seq)
        return super().create(vals_list)

    def action_octroyer_avance(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.avance', 'view_mode': 'form',
                'context': {'default_partner_id': self.id}}

    def action_open_avances(self):
        return {'type': 'ir.actions.act_window', 'name': 'Avances', 'res_model': 'ka.avance',
                'view_mode': 'tree,form', 'domain': [('partner_id', '=', self.id)]}

    def action_open_tickets(self):
        return {'type': 'ir.actions.act_window', 'name': 'Tickets de pesée', 'res_model': 'ka.ticket',
                'view_mode': 'tree,form', 'domain': [('partner_id', '=', self.id)]}

    def action_open_decomptes(self):
        return {'type': 'ir.actions.act_window', 'name': 'Décomptes', 'res_model': 'account.move',
                'view_mode': 'tree,form',
                'domain': [('partner_id', '=', self.id), ('move_type', '=', 'in_invoice')]}

    def action_open_compte_courant(self):
        return {'type': 'ir.actions.act_window', 'name': 'Compte courant planteur',
                'res_model': 'account.move.line', 'view_mode': 'tree,form',
                'domain': [('partner_id', '=', self.id), ('account_id.account_type', 'in',
                           ('liability_payable', 'asset_receivable'))]}


class KaParcelle(models.Model):
    _name = 'ka.parcelle'
    _description = 'Parcelle géolocalisée (EUDR)'

    partner_id = fields.Many2one('res.partner', required=True, ondelete='cascade')
    name = fields.Char(string='Référence', required=True)
    surface = fields.Float(string='Surface (ha)', digits=(8, 1))
    latitude = fields.Float(digits=(3, 4))
    longitude = fields.Float(digits=(4, 4))
    clone = fields.Char(string='Clone')
    statut_eudr = fields.Selection([
        ('conforme', 'Conforme'), ('a_verifier', 'À vérifier'), ('non_conforme', 'Non conforme'),
    ], string='Statut EUDR', default='a_verifier', required=True)
