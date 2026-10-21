from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class KaLettrage(models.Model):
    """Lettrage d'un compte de tiers : proposition puis lettrage automatique (écran 8.5)."""
    _name = 'ka.lettrage'
    _description = 'Lettrage automatique'
    _inherit = ['ka.document']
    _order = 'id desc'

    company_id = fields.Many2one('res.company', string='Société', default=lambda s: s.env.company)
    account_id = fields.Many2one('account.account', string='Collectif', required=True)
    partner_id = fields.Many2one('res.partner', string='Tiers', required=True)
    critere = fields.Selection([('reference', 'Référence avance'), ('montant', 'Montant'), ('echeance', 'Échéance')],
                               string='Critère de lettrage', default='reference')
    line_ids = fields.One2many('ka.lettrage.ligne', 'lettrage_id', string='Écritures')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    solde = fields.Monetary(compute='_compute_solde', string='Solde dû après lettrage')
    state = fields.Selection([('non_lettre', 'Non lettré'), ('partiel', 'Partiellement lettré'), ('lettre', 'Lettré')],
                             compute='_compute_solde', string='Statut')

    def _ka_subtitle(self):
        self.ensure_one()
        code = self.partner_id.ka_code or self.partner_id.ref or ''
        return '%s %s — collectif %s' % (code, self.partner_id.name or '', self.account_id.name or '')

    @api.depends('line_ids.debit', 'line_ids.credit', 'line_ids.lettre')
    def _compute_solde(self):
        for l in self:
            l.solde = sum(l.line_ids.mapped('debit')) - sum(l.line_ids.mapped('credit'))
            lettres = l.line_ids.mapped('lettre')
            l.state = 'non_lettre' if not any(lettres) else ('lettre' if all(lettres) and abs(l.solde) < 0.5 else 'partiel')

    def _domaine(self):
        self.ensure_one()
        return [('partner_id', '=', self.partner_id.id), ('account_id', '=', self.account_id.id), ('parent_state', '=', 'posted')]

    def action_proposer(self):
        """Charge les écritures du tiers sur le collectif (lettrées ou non) pour examen avant lettrage."""
        for l in self:
            lignes = self.env['account.move.line'].search(l._domaine(), order='date, id')
            l.line_ids.unlink()
            l.line_ids = [Command.create({'aml_id': x.id}) for x in lignes]

    def action_lettrer(self):
        """Lettrage automatique standard : rapproche débits et crédits ouverts du tiers (partiel si besoin)."""
        for l in self:
            ouvertes = self.env['account.move.line'].search(l._domaine() + [('reconciled', '=', False)])
            if len(ouvertes) < 2 or not (ouvertes.filtered(lambda x: x.balance > 0) and ouvertes.filtered(lambda x: x.balance < 0)):
                raise UserError(_("Aucun débit et crédit ouverts à rapprocher pour ce tiers."))
            ouvertes.reconcile()
            l.action_proposer()

    def action_balance_agee(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Balance âgée', 'res_model': 'account.move.line',
                'view_mode': 'list', 'domain': self._domaine() + [('reconciled', '=', False)]}


class KaLettrageLigne(models.Model):
    _name = 'ka.lettrage.ligne'
    _description = 'Écriture à lettrer'
    _order = 'date, id'

    lettrage_id = fields.Many2one('ka.lettrage', required=True, ondelete='cascade')
    aml_id = fields.Many2one('account.move.line', string='Écriture', required=True)
    date = fields.Date(related='aml_id.date', string='Date', store=True)
    piece = fields.Char(related='aml_id.move_name', string='Pièce')
    intitule = fields.Char(related='aml_id.name', string='Intitulé')
    # Float calculés (et non liés) : account.move.line.debit est un champ Monetary, un champ lié doit avoir le même type
    debit = fields.Float(compute='_compute_montants', string='Débit', digits=(14, 0), store=True)
    credit = fields.Float(compute='_compute_montants', string='Crédit', digits=(14, 0), store=True)
    lettre = fields.Char(compute='_compute_lettre', string='Lettre', store=False)

    @api.depends('aml_id.debit', 'aml_id.credit')
    def _compute_montants(self):
        for x in self:
            x.debit, x.credit = x.aml_id.debit, x.aml_id.credit

    @api.depends('aml_id.matching_number')
    def _compute_lettre(self):
        for x in self:
            x.lettre = x.aml_id.matching_number or ''
