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
    mode = fields.Selection([('vir', 'VIR — Virement bancaire')], string='Mode de règlement', required=True,
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
    state = fields.Selection([('brouillon', 'Brouillon'), ('approuvee', 'Approuvée'),
                              ('remise', 'Remise générée'), ('transmise', 'Transmise à la banque')],
                             default='brouillon', string='Statut')
    fichier = fields.Binary(string='Fichier de virement', readonly=True)
    fichier_nom = fields.Char()

    def _ka_subtitle(self):
        self.ensure_one()
        if not self.date_debut:
            return self.name
        return '%s — %s du %s au %s' % (self.name, self.libelle or '', self.date_debut.strftime('%d/%m'),
                                         self.date_fin.strftime('%d/%m/%Y') if self.date_fin else '')

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

    @api.onchange('date_debut', 'date_fin', 'categorie', 'mode')
    def _onchange_criteres(self):
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

    def action_approuver(self):
        if not self.line_ids:
            raise UserError(_('La proposition ne contient aucune ligne.'))
        self.write({'state': 'approuvee'})

    def action_generer_reglements(self):
        self.ensure_one()
        if self.state != 'approuvee':
            raise UserError(_("La proposition doit être approuvée avant de générer les règlements."))
        for line in self.line_ids:
            wiz = self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=line.move_id.ids).create({
                    'journal_id': self.journal_id.id, 'amount': line.net,
                    'payment_date': self.date_fin, 'communication': self.name})
            payments = wiz._create_payments()
            line.payment_id = payments[:1]
        self.state = 'remise'

    def action_fichier_virement(self):
        self.ensure_one()
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=';')
        w.writerow(['Beneficiaire', 'Banque / IBAN', 'Facture', 'Montant'])
        for l in self.line_ids:
            w.writerow([l.partner_id.display_name, l.banque, l.move_id.name, int(l.net)])
        self.write({'fichier': base64.b64encode(buf.getvalue().encode()),
                    'fichier_nom': '%s_virement.csv' % self.name, 'state': 'transmise'})

    def action_comptabiliser(self):
        self.ensure_one()
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
