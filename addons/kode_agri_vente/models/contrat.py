import math
import re

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
    _inherit = ['ka.document', 'mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(string='N° contrat', readonly=True, copy=False, default='Nouveau')
    type = fields.Selection([('spot', 'Spot'), ('clt', 'Long terme')],
                            string='Type de contrat', required=True, default='clt')
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
    state = fields.Selection([('en_cours', 'Devis'), ('a_signer', 'Devis envoyé'), ('signee', 'Bon de commande'),
                              ('soldee', 'Verrouillée'), ('refusee', 'Refusée')], default='en_cours', string='Statut',
                             tracking=True)
    badge_label = fields.Char(compute='_compute_badge')
    # écrans 5.2 / 5.2b (v4.5) : cartes KPI et conversion des quantités
    ctn_kpi = fields.Char(compute='_compute_conversion', string='Conteneurs (carte)')
    balles_kpi = fields.Char(compute='_compute_conversion', string='Balles (carte)')
    conteneurs_txt = fields.Char(compute='_compute_conversion', string='→ Conteneurs')
    balles_txt = fields.Char(compute='_compute_conversion', string='→ Balles')
    restant_kg_txt = fields.Char(compute='_compute_conversion', string='Restant à affecter (kg)')
    restant_ctn_txt = fields.Char(compute='_compute_conversion', string='Restant à affecter (conteneurs)')
    grade_code = fields.Char(related='product_id.default_code', string='Grade')
    spec_titre = fields.Char(compute='_compute_spec_mode', string='Titre des spécifications')
    spec_edition = fields.Boolean(string='Spécifications en cours de modification', copy=False)

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — %s · %s' % (self.name, self.partner_id.name or '', 'contrat Long terme' if self.type == 'clt' else 'vente Spot')

    @api.depends('state')
    def _compute_badge(self):
        for c in self:
            c.badge_label = {'en_cours': 'En cours', 'a_signer': 'À signer (DG)', 'signee': 'Signée',
                             'soldee': 'Soldée', 'refusee': 'Refusée'}[c.state]

    @api.depends('type', 'product_id')
    def _compute_spec_mode(self):
        for c in self:
            c.spec_mode = 'Éditable' if c.type == 'spot' else 'Héritées'
            c.spec_source = 'Contrat (modifiable)' if c.type == 'spot' else 'Fiche client'
            grade = c.product_id.default_code or ''
            c.spec_titre = ('Spécifications du contrat Spot — éditables (priment sur la fiche client)' if c.type == 'spot'
                            else 'Spécifications — 7 tests (standard %s ; fiche client prioritaire)' % grade)

    @api.depends('name', 'partner_id', 'type')
    @api.depends_context('ka_nom_long_contrat')
    def _compute_display_name(self):
        """Fil d'Ariane des maquettes v4.5 : « CV-0061 — TyreCorp » (« (Spot) » pour un contrat Spot)."""
        long = self.env.context.get('ka_nom_long_contrat')
        for c in self:
            if long and c.partner_id:
                c.display_name = '%s — %s%s' % (c.name, c.partner_id.name, ' (Spot)' if c.type == 'spot' else '')
            else:
                c.display_name = c.name or ''

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
            restant_ctn = math.ceil(restant / cap) if cap and restant > 0 else 0
            c.restant_txt = '%s kg (%s ctn)' % (fmt_int(restant), restant_ctn)
            c.ctn_kpi = '%s ctn' % c.nb_conteneurs
            c.balles_kpi = fmt_int(c.nb_balles)
            c.conteneurs_txt = '%s conteneurs' % c.nb_conteneurs
            c.balles_txt = '%s balles' % fmt_int(c.nb_balles)
            c.restant_kg_txt = '%s kg' % fmt_int(restant)
            c.restant_ctn_txt = '%s conteneurs' % restant_ctn

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
                'context': {'default_contrat_id': self.id, 'ka_nom_long_sc': True}}

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

    def action_open_conteneurs(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Conteneurs', 'res_model': 'ka.conteneur',
                'view_mode': 'list,form', 'domain': [('sous_contrat_id.contrat_id', '=', self.id)]}

    def action_open_client(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Clients', 'res_model': 'res.partner', 'res_id': self.partner_id.id,
                'view_mode': 'form', 'views': [(self.env.ref('kode_agri_vente.view_ka_client_form').id, 'form')]}

    def action_modifier_specs(self):
        """Contrat Spot (écran 5.2b) : la logistique ouvre les spécifications du contrat à la modification."""
        for c in self:
            if c.type != 'spot':
                raise UserError(_('Seules les spécifications d\'un contrat Spot sont modifiables (RG-5.3).'))
            c.write({'spec_edition': not c.spec_edition, 'modifie_par': self.env.user.name})

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
    modifie_txt = fields.Char(compute='_compute_modifie', string='Modifié ')
    vmin_txt = fields.Char(compute='_compute_bornes', string='Min')
    vmax_txt = fields.Char(compute='_compute_bornes', string='Max')

    @api.depends('applique')
    def _compute_bornes(self):
        """Bornes affichées sur l'équivalent conteneur (écran 5.4) : « ≥ 30 » → Min, « ≤ 0,80 » → Max, « 65 – 85 »."""
        for s in self:
            txt = (s.applique or '').strip()
            vmin = vmax = '—'
            m = re.match(r'^([≥≤])\s*([\d.,]+)$', txt)
            r = re.match(r'^\[?([\d.,]+)\s*[–-]\s*([\d.,]+)\]?$', txt)
            if m and m.group(1) == '≥':
                vmin = txt
            elif m:
                vmax = m.group(2)
            elif r:
                vmin, vmax = r.group(1), r.group(2)
            elif txt and txt.upper() != 'NAP' and not txt.lower().startswith(('selon', 'varie')):
                vmin = txt
            s.vmin_txt, s.vmax_txt = vmin, vmax

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
            s.modifie_txt = 'Oui' if s.modifie else '—'
