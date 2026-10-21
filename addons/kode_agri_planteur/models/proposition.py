import base64
import csv
import io

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class KaProposition(models.Model):
    _name = 'ka.proposition'
    _description = 'Proposition de règlement — virement multiple'
    _inherit = ['ka.document']
    _order = 'name desc'

    name = fields.Char(string='N° proposition', readonly=True, copy=False, default='Nouveau')
    libelle = fields.Char(string='Libellé', default='quinzaine')
    journal_id = fields.Many2one('account.journal', string='Banque émettrice', required=True,
                                 domain=[('type', '=', 'bank')])
    mode = fields.Selection([('vir', 'Virement bancaire')], string='Mode de règlement', required=True,
                            default='vir')
    date_debut = fields.Date(string='Date début', required=True)
    date_fin = fields.Date(string='Date fin', required=True)
    categorie = fields.Selection([('planteur_coop', 'Planteur & coopérative')], string='Catégorie fournisseur',
                                 default='planteur_coop')
    exclus = fields.Char(string='Exclus', compute='_compute_exclus')
    format_bancaire = fields.Char(string='Format bancaire', default='Virement de masse SGBCI')
    circuit = fields.Char(string='Circuit', default='Workflow trésorerie', readonly=True)
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    line_ids = fields.One2many('ka.proposition.line', 'proposition_id', string='Lignes de la proposition')
    total = fields.Monetary(compute='_compute_total', string='Net total')
    nb_beneficiaires = fields.Integer(compute='_compute_total', string='Bénéficiaires')
    state = fields.Selection([('brouillon', 'Brouillon'), ('a_approuver', 'À approuver'), ('approuvee', 'Approuvé'),
                              ('remise', 'Règlements générés'), ('transmise', 'Transmis banque')],
                             default='brouillon', string='Statut')
    compte_emetteur = fields.Char(related='journal_id.bank_acc_number', string='N° compte émetteur')
    nb_beneficiaires_txt = fields.Char(compute='_compute_total', string='Bénéficiaires éligibles')
    total_txt = fields.Char(compute='_compute_total', string='Net total (abrégé)')
    fichier = fields.Binary(string='Fichier de virement', readonly=True)
    fichier_nom = fields.Char()

    def _ka_subtitle(self):
        self.ensure_one()
        if not (self.date_debut and self.date_fin):
            return 'Routine — %s' % (self.libelle or '')
        debut = self.date_debut.strftime('%d' if self.date_debut.strftime('%m%Y') == self.date_fin.strftime('%m%Y')
                                         else '%d/%m/%Y')
        return 'Routine — %s %s–%s' % (self.libelle or '', debut, self.date_fin.strftime('%d/%m/%Y'))

    @api.depends('name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s — Virement multiple' % (rec.name or '')

    @api.depends('date_debut', 'date_fin', 'categorie')
    def _compute_exclus(self):
        for rec in self:
            n = self.env['res.partner'].search_count([('ka_categorie', '=', rec.categorie),
                                                      ('ka_mode_reglement', 'in', ('chq', 'caisse'))])
            rec.exclus = '%s (chèque / caisse)' % n

    @api.depends('line_ids.net')
    def _compute_total(self):
        for rec in self:
            rec.total = sum(rec.line_ids.mapped('net'))
            rec.nb_beneficiaires = len(rec.line_ids.mapped('partner_id'))
            rec.nb_beneficiaires_txt = '%d éligible%s' % (rec.nb_beneficiaires, 's' if rec.nb_beneficiaires > 1 else '')
            t = rec.total
            if abs(t) >= 1_000_000:
                rec.total_txt = ('%.1f M' % (t / 1_000_000)).replace('.', ',')
            elif abs(t) >= 1000:
                rec.total_txt = '%d k' % round(t / 1000)
            else:
                rec.total_txt = '%d' % t

    @api.onchange('date_debut', 'date_fin', 'categorie', 'mode')
    def _onchange_criteres(self):
        self._charger_lignes()

    def _charger_lignes(self):
        if not (self.date_debut and self.date_fin):
            return
        moves = self.env['account.move'].search([
            ('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('invoice_date', '>=', self.date_debut), ('invoice_date', '<=', self.date_fin),
            ('partner_id.ka_categorie', '=', self.categorie),
            ('partner_id.ka_mode_reglement', 'in', ('vir', 'mobile'))])
        self.line_ids = [Command.clear()] + [Command.create({
            'partner_id': m.partner_id.id, 'move_id': m.id, 'net': m.amount_residual,
            'banque': m.partner_id.bank_ids[:1].display_name or ''}) for m in moves]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.proposition')
        return super().create(vals_list)

    def action_lancer_routine(self):
        """Routine de période : charge les nets à payer des planteurs en mode virement et soumet l'ordre."""
        for rec in self:
            if rec.state not in ('brouillon', 'a_approuver'):
                raise UserError(_("L'ordre de virement est déjà approuvé."))
            rec._charger_lignes()
            rec.state = 'a_approuver'

    def action_open_beneficiaires(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Bénéficiaires', 'res_model': 'res.partner',
                'view_mode': 'list,form', 'domain': [('id', 'in', self.line_ids.partner_id.ids)]}

    def action_open_factures(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Factures réglées', 'res_model': 'account.move',
                'view_mode': 'list,form', 'domain': [('id', 'in', self.line_ids.move_id.ids)]}

    def action_approuver(self):
        if not self.line_ids:
            raise UserError(_('La proposition ne contient aucune ligne.'))
        self.write({'state': 'approuvee'})

    def action_generer_reglements(self):
        self.ensure_one()
        if self.state not in ('approuvee', 'remise', 'transmise'):
            raise UserError(_("L'ordre de virement doit être approuvé avant de générer les règlements."))
        for line in self.line_ids.filtered(lambda l: not l.payment_id and l.move_id):
            wiz = self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=line.move_id.ids).create({
                    'journal_id': self.journal_id.id, 'amount': line.net,
                    'payment_date': self.date_fin, 'communication': self.name})
            payments = wiz._create_payments()
            line.payment_id = payments[:1]
        if self.state == 'approuvee':
            self.state = 'remise'

    def action_fichier_virement(self):
        self.ensure_one()
        if self.state in ('brouillon', 'a_approuver'):
            raise UserError(_("L'ordre de virement doit être approuvé avant de générer le fichier de virement."))
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=';')
        w.writerow(['Beneficiaire', 'Banque / IBAN', 'Facture', 'Montant'])
        for l in self.line_ids:
            w.writerow([l.partner_id.display_name, l.banque, l.move_id.name, int(l.net)])
        self.write({'fichier': base64.b64encode(buf.getvalue().encode()),
                    'fichier_nom': '%s_virement.csv' % self.name, 'state': 'transmise'})

    def action_comptabiliser(self):
        self.ensure_one()
        if self.line_ids.filtered(lambda l: not l.payment_id and l.move_id):
            self.action_generer_reglements()
        self.line_ids.payment_id.filtered(lambda p: p.state == 'draft').action_post()


class KaPropositionLine(models.Model):
    _name = 'ka.proposition.line'
    _description = 'Ligne de proposition de règlement'

    proposition_id = fields.Many2one('ka.proposition', required=True, ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string='Bénéficiaire', required=True)
    banque = fields.Char(string='Banque / IBAN')
    move_id = fields.Many2one('account.move', string='Facture')
    currency_id = fields.Many2one(related='proposition_id.currency_id')
    net = fields.Monetary(string='Net à payer')
    payment_id = fields.Many2one('account.payment', readonly=True)
