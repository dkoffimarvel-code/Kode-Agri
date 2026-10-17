from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class KaFraisReglement(models.Model):
    """Remboursement du collaborateur par virement, soldant son compte 421000 (§ 6.1 étape 5)."""
    _name = 'ka.frais.reglement'
    _description = 'Règlement — remboursement de note de frais'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° règlement', readonly=True, copy=False, default='Nouveau')
    note_id = fields.Many2one('ka.frais.note', string='Note de frais', required=True)
    type_reglement = fields.Selection([('vir', 'VIR — Virement salarié')], string='Type de règlement',
                                      required=True, default='vir')
    salarie_id = fields.Many2one('res.partner', string='Tiers', required=True)
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    montant = fields.Monetary(string='Montant', required=True)
    date = fields.Date(string='Date', default=fields.Date.context_today)
    journal_id = fields.Many2one('account.journal', string='Banque', domain=[('type', '=', 'bank')])
    iban = fields.Char(compute='_compute_iban', string='IBAN du salarié')
    payment_id = fields.Many2one('account.payment', readonly=True, copy=False)
    piece_ids = fields.One2many('ka.frais.piece', 'reglement_id', string='Pièce générée')
    state = fields.Selection([('propose', 'À régler'), ('rembourse', 'Remboursée')], default='propose',
                             string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        d = self.date.strftime('%d/%m/%Y') if self.date else ''
        return '%s — %s · virement du %s' % (self.name, self.note_id.name or '', d)

    @api.depends('salarie_id')
    def _compute_iban(self):
        for r in self:
            acc = r.salarie_id.bank_ids[:1].acc_number or ''
            r.iban = ('%s •••• %s' % (acc[:4], acc[-4:])) if len(acc) > 8 else acc

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.frais.reglement')
        return super().create(vals_list)

    def action_regler(self):
        """Paiement fournisseur du salarié, lettré avec la dette 421000 de la note de frais."""
        for r in self:
            if r.state != 'propose':
                continue
            if not r.journal_id:
                raise UserError(_('Choisissez la banque émettrice.'))
            note = r.note_id
            payment = self.env['account.payment'].create({
                'payment_type': 'outbound', 'partner_type': 'supplier', 'partner_id': r.salarie_id.id,
                'journal_id': r.journal_id.id, 'amount': r.montant, 'date': r.date, 'ref': '%s — %s' % (r.name, note.name),
                'destination_account_id': note._compte('421000').id})
            payment.action_post()
            dette = (note.move_id.line_ids | payment.move_id.line_ids).filtered(
                lambda l: l.account_id.code == '421000' and not l.reconciled)
            if len(dette) >= 2:
                dette.reconcile()
            r.piece_ids.unlink()
            r.write({'payment_id': payment.id, 'state': 'rembourse', 'piece_ids': [
                Command.create({'compte': '421000', 'intitule': 'Solde note de frais %s' % note.name, 'debit': r.montant}),
                Command.create({'compte': r.journal_id.default_account_id.code or '521000',
                                'intitule': 'Virement %s — %s' % (r.salarie_id.name, r.name), 'credit': r.montant})]})
            note.state = 'remboursee'

    def action_imprimer(self):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Avis de virement'), 'type': 'success', 'sticky': False,
                           'message': _('Avis de virement imprimé.')}}

    def action_voir_piece(self):
        self.ensure_one()
        if not self.payment_id:
            raise UserError(_('Aucune pièce : réglez d\'abord la note.'))
        return {'type': 'ir.actions.act_window', 'res_model': 'account.payment', 'res_id': self.payment_id.id,
                'view_mode': 'form'}
