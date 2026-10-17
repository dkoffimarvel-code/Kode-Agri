import math

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import (EMBALLAGES, GRILLE, LIBELLES, PAIEMENTS, POIDS_COLIS, TAUX_CHANGE_EUR_XOF, TESTS_SPEC,
                     ka_param)


def fmt_int(x):
    return '{:,.0f}'.format(x).replace(',', ' ')


class KaContrat(models.Model):
    """Commande ouverte : contrat Spot ou Long terme (§ 5.2.1). Le Spot est répercuté en commande client."""
    _name = 'ka.contrat'
    _description = 'Contrat de vente'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° contrat', readonly=True, copy=False, default='Nouveau')
    type = fields.Selection([('spot', 'CSP — Contrat Spot'), ('clt', 'CLT — Contrat Long terme')],
                            string='Type de commande', required=True, default='clt')
    partner_id = fields.Many2one('res.partner', string='Client', required=True, domain=[('ka_client', '=', True)])
    product_id = fields.Many2one('product.product', string='Article', required=True,
                                 domain=[('default_code', 'in', ('TSR10', 'TSR20', 'OFFSPECS'))])
    tracabilite = fields.Selection([('eudr', 'EUDR'), ('non_eudr', 'NON EUDR')], string='Statut de traçabilité',
                                   required=True, default='eudr')
    qty_kg = fields.Float(string='Quantité (kg)', digits=(12, 0), required=True)
    currency_id = fields.Many2one('res.currency', string='Devise', required=True,
                                  default=lambda s: s.env.ref('base.EUR', raise_if_not_found=False))
    company_currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    prix_t = fields.Float(string='Prix de vente', digits=(10, 0), required=True)
    montant = fields.Monetary(string='Montant en devise', compute='_compute_montant', store=True)
    contre_valeur = fields.Monetary(string='Contre-valeur', compute='_compute_montant', store=True,
                                    currency_field='company_currency_id')
    periode = fields.Char(string="Période d'embarquement", required=True)
    incoterm = fields.Char(string='Incoterm', required=True)
    ref_client = fields.Char(string='Réf. contrat client')
    paiement = fields.Selection(PAIEMENTS, string='Condition de paiement')
    emballage = fields.Selection(EMBALLAGES, string="Type d'emballage", default='palette')
    conditions = fields.Char(string='Conditions contrat', default='International TSR contracts')
    port = fields.Char(string="Port d'embarquement", default='Abidjan')
    warehouse_id = fields.Many2one('stock.warehouse', string='Code usine')
    spec_ids = fields.One2many('ka.contrat.spec', 'contrat_id', string='Spécifications')
    sous_contrat_ids = fields.One2many('ka.sous.contrat', 'contrat_id', string='Sous-contrats')
    nb_conteneurs = fields.Integer(compute='_compute_conversion', string='Conteneurs')
    nb_balles = fields.Integer(compute='_compute_conversion', string='Balles')
    restant_txt = fields.Char(compute='_compute_conversion', string='Restant à affecter')
    spec_mode = fields.Char(compute='_compute_spec_mode', string='Spécifications')
    modifie_par = fields.Char(string='Modifié par', default='Logistique export', readonly=True)
    spec_source = fields.Char(compute='_compute_spec_mode', string='Source des spécifications')
    sale_order_id = fields.Many2one('sale.order', string='Commande client', readonly=True, copy=False)
    state = fields.Selection([('en_cours', 'En cours'), ('a_signer', 'À signer'), ('signee', 'Signée'),
                              ('soldee', 'Soldée'), ('refusee', 'Refusée')], default='en_cours', string='Statut',
                             tracking=True)
    badge_label = fields.Char(compute='_compute_badge')

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — %s · %s' % (self.name, self.partner_id.name or '', 'contrat Long terme' if self.type == 'clt' else 'vente Spot')

    @api.depends('state')
    def _compute_badge(self):
        for c in self:
            c.badge_label = {'en_cours': 'En cours', 'a_signer': 'À signer (DG)', 'signee': 'Signée',
                             'soldee': 'Soldée', 'refusee': 'Refusée'}[c.state]

    @api.depends('type')
    def _compute_spec_mode(self):
        for c in self:
            c.spec_mode = 'Modifiables' if c.type == 'spot' else 'Héritées'
            c.spec_source = 'Contrat (modifiable)' if c.type == 'spot' else 'Fiche client'

    @api.depends('qty_kg', 'prix_t', 'currency_id')
    def _compute_montant(self):
        for c in self:
            c.montant = c.qty_kg / 1000.0 * c.prix_t
            rate = 1.0
            if c.currency_id and c.currency_id != c.company_currency_id:
                rate = c.currency_id._get_conversion_rate(c.currency_id, c.company_currency_id, self.env.company,
                                                          fields.Date.context_today(c))
                if c.currency_id.name == 'EUR' and c.company_currency_id.name == 'XOF' and abs(rate - 1.0) < 1e-6:
                    rate = TAUX_CHANGE_EUR_XOF   # parité fixe FCFA/EUR si aucun cours n'est saisi
            c.contre_valeur = c.montant * rate

    def capacite_kg(self):
        """Capacité d'un conteneur : 16 colis en palette, 17 en vrac (RG-5.12, paramétrable)."""
        self.ensure_one()
        colis = ka_param(self.env, 'colis_vrac', 17.0) if self.emballage == 'vrac' else ka_param(self.env, 'colis_palette', 16.0)
        return colis * POIDS_COLIS

    @api.depends('qty_kg', 'emballage', 'sous_contrat_ids.poids_kg')
    def _compute_conversion(self):
        """RG-5.4 : kg → conteneurs et balles (35 kg / balle, 36 balles / colis)."""
        for c in self:
            cap = c.capacite_kg()
            c.nb_conteneurs = math.ceil(c.qty_kg / cap) if cap and c.qty_kg else 0
            colis_par_ctn = cap / POIDS_COLIS if cap else 0
            c.nb_balles = int(c.nb_conteneurs * colis_par_ctn * 36)
            restant = c.qty_kg - sum(c.sous_contrat_ids.mapped('poids_kg'))
            c.restant_txt = '%s kg (%s ctn)' % (fmt_int(restant), math.ceil(restant / cap) if cap and restant > 0 else 0)

    # ---- spécifications (RG-5.3 / RG-5.5) -----------------------------------------------------------
    def _refresh_specs(self, force=False):
        for c in self:
            grade = GRILLE.get(c.product_id.default_code or '', {})
            client = {s.test: s.texte for s in c.partner_id.ka_spec_ids}
            existants = {s.test: s for s in c.spec_ids}
            cmds = []
            for test, _label in TESTS_SPEC:
                standard = grade.get(test, '')
                initial = client.get(test) or standard
                line = existants.get(test)
                if line and line.modifie and not force:
                    cmds.append(Command.update(line.id, {'standard': standard}))
                elif line:
                    cmds.append(Command.update(line.id, {'standard': standard, 'initial': initial, 'applique': initial}))
                else:
                    cmds.append(Command.create({'test': test, 'standard': standard, 'initial': initial, 'applique': initial}))
            c.spec_ids = cmds

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.contrat')
        recs = super().create(vals_list)
        recs._refresh_specs()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if 'partner_id' in vals or 'product_id' in vals:
            self._refresh_specs()   # RG-5.5 : mise à jour à l'affectation du client final
        return res

    # ---- workflow (RG-5.9) ---------------------------------------------------------------------------------
    def action_soumettre(self):
        for c in self:
            if c.state != 'en_cours':
                raise UserError(_('Seul un contrat « En cours » peut être soumis à signature.'))
            c.state = 'a_signer'
            c.activity_schedule('mail.mail_activity_data_todo', summary=_('Contrat %s à signer') % c.name,
                                user_id=self.env.user.id)

    def action_signer(self):
        for c in self.filtered(lambda c: c.state == 'a_signer'):
            c.state = 'signee'
            if c.type == 'spot':
                c._creer_commande_client()

    def action_refuser(self):
        self.filtered(lambda c: c.state == 'a_signer').write({'state': 'refusee'})

    def _creer_commande_client(self):
        """Contrat Spot : commande client Odoo standard (prix converti en devise société, au kg)."""
        for c in self:
            if c.sale_order_id:
                continue
            prix_kg = (c.contre_valeur / c.qty_kg) if c.qty_kg else 0.0
            c.sale_order_id = self.env['sale.order'].create({
                'partner_id': c.partner_id.id, 'client_order_ref': c.ref_client or c.name, 'origin': c.name,
                'order_line': [Command.create({'product_id': c.product_id.id, 'product_uom_qty': c.qty_kg,
                                               'price_unit': prix_kg})]})

    def action_creer_sous_contrat(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.sous.contrat', 'view_mode': 'form',
                'views': [(self.env.ref('kode_agri_vente.view_ka_sc_form').id, 'form')],
                'context': {'default_contrat_id': self.id}}

    def action_imprimer(self):
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Contrat'), 'type': 'success', 'sticky': False,
                           'message': _('Contrat %s envoyé à l\'impression.') % self.name}}

    def action_open_sous_contrats(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Sous-contrats', 'res_model': 'ka.sous.contrat',
                'view_mode': 'list,form', 'domain': [('contrat_id', '=', self.id)],
                'context': {'default_contrat_id': self.id}}

    def action_open_livraisons(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Livraisons', 'res_model': 'ka.livraison',
                'view_mode': 'list,form', 'domain': [('sous_contrat_id.contrat_id', '=', self.id)]}

    def action_open_factures(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Factures', 'res_model': 'account.move',
                'view_mode': 'list,form', 'domain': [('invoice_origin', 'ilike', self.name)]}


class KaContratSpec(models.Model):
    _name = 'ka.contrat.spec'
    _description = 'Spécification du contrat (7 tests)'
    _order = 'id'

    contrat_id = fields.Many2one('ka.contrat', required=True, ondelete='cascade')
    test = fields.Selection(TESTS_SPEC, required=True, string='Test')
    libelle = fields.Char(compute='_compute_libelle', string='Libellé')
    standard = fields.Char(string='Standard')
    initial = fields.Char(string='Valeur héritée')
    applique = fields.Char(string='Appliqué (contrat)')
    modifie = fields.Boolean(compute='_compute_modifie', string='Modifié', store=True)
    source = fields.Char(compute='_compute_modifie', string='Source')

    @api.depends('test')
    def _compute_libelle(self):
        for s in self:
            s.libelle = LIBELLES.get(s.test, '')

    @api.depends('applique', 'initial')
    def _compute_modifie(self):
        """RG-5.3 : la valeur saisie sur le contrat prime sur la fiche client."""
        for s in self:
            s.modifie = (s.applique or '') != (s.initial or '')
            s.source = 'Contrat' if s.modifie else 'Fiche client'
