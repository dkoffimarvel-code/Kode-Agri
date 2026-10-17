from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class KaCheque(models.Model):
    _name = 'ka.cheque'
    _description = 'Règlement fournisseur — chèque'
    _inherit = ['ka.document']
    _order = 'name desc'

    name = fields.Char(string='Référence', readonly=True, copy=False, default='Nouveau')
    type_reglement = fields.Selection([('chq', 'CHQ — Chèque fournisseur')], string='Type de règlement',
                                      required=True, default='chq')
    partner_id = fields.Many2one('res.partner', string='Tiers', required=True)
    journal_id = fields.Many2one('account.journal', string='Banque', required=True,
                                 domain=[('type', '=', 'bank')])
    date = fields.Date(required=True, default=fields.Date.context_today)
    numero_cheque = fields.Char(string='N° de chèque', required=True)
    decompte = fields.Char(string='Décompte', help='Référence du décompte réglé (DEC-xxxx)')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    detail_ids = fields.One2many('ka.cheque.line', 'cheque_id', string='Détail du net réglé')
    amount = fields.Monetary(string='Montant', compute='_compute_amount', store=True)
    amount_words = fields.Char(string='Montant en lettres', compute='_compute_words')
    payment_id = fields.Many2one('account.payment', readonly=True, copy=False)
    state = fields.Selection([('a_imprimer', 'À imprimer'), ('imprime', 'Imprimé'),
                              ('comptabilise', 'Comptabilisé'), ('lettre', 'Lettré')],
                             default='a_imprimer', string='Statut')

    def _ka_subtitle(self):
        return '%s — règlement du décompte %s' % (self.numero_cheque and self.name or self.name,
                                                  self.decompte or '')

    @api.depends('detail_ids.montant')
    def _compute_amount(self):
        for rec in self:
            rec.amount = sum(rec.detail_ids.mapped('montant'))

    @api.depends('amount', 'currency_id')
    def _compute_words(self):
        for rec in self:
            try:
                rec.amount_words = rec.currency_id.with_context(lang='fr_FR').amount_to_text(rec.amount)
            except Exception:
                rec.amount_words = ''

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.cheque')
        return super().create(vals_list)

    def action_imprimer(self):
        self.write({'state': 'imprime'})

    def action_comptabiliser(self):
        for rec in self:
            payment = self.env['account.payment'].create({
                'payment_type': 'outbound', 'partner_type': 'supplier', 'partner_id': rec.partner_id.id,
                'journal_id': rec.journal_id.id, 'amount': rec.amount, 'date': rec.date,
                'ref': rec.numero_cheque})
            payment.action_post()
            rec.write({'payment_id': payment.id, 'state': 'comptabilise'})

    def action_lettrer(self):
        for rec in self:
            if not rec.payment_id:
                raise UserError(_("Comptabilisez le chèque avant de le lettrer."))
            lines = (rec.payment_id.line_ids | self.env['account.move.line'].search([
                ('partner_id', '=', rec.partner_id.id), ('parent_state', '=', 'posted'),
                ('reconciled', '=', False), ('account_id.reconcile', '=', True),
                ('account_id', 'in', rec.payment_id.line_ids.account_id.ids)])).filtered(
                    lambda l: not l.reconciled and l.account_id.reconcile)
            lines.reconcile()
            rec.state = 'lettre'


class KaChequeLine(models.Model):
    _name = 'ka.cheque.line'
    _description = 'Détail du net réglé'
    _order = 'sequence, id'

    cheque_id = fields.Many2one('ka.cheque', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    element = fields.Char(string='Élément', required=True)
    detail = fields.Char(string='Détail')
    currency_id = fields.Many2one(related='cheque_id.currency_id')
    montant = fields.Monetary(string='Montant')
