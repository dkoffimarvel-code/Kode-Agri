from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .immo import fin_de_mois


def compte(env, code):
    acc = env['account.account'].search([('code', '=', code)], limit=1)
    if not acc:
        raise UserError(_("Le compte %s est introuvable dans le plan comptable.") % code)
    return acc


class KaImmoDotation(models.Model):
    """Traitement de comptabilisation des dotations d'une période (écran 3.4)."""
    _name = 'ka.immo.dotation'
    _description = 'Comptabilisation des dotations'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° traitement', readonly=True, copy=False, default='Nouveau')
    company_id = fields.Many2one('res.company', string='Société', required=True, default=lambda s: s.env.company)
    plan = fields.Selection([('comptable', 'Comptable')], string="Plan d'amortissement", required=True, default='comptable')
    periode = fields.Date(string='Période', required=True, help="Dernier jour de la période à comptabiliser")
    journal_id = fields.Many2one('account.journal', string='Journal', domain=[('type', '=', 'general')])
    type_piece = fields.Char(string='Type de pièce', default='DOT — Dotation')
    date_piece = fields.Date(string='Date de pièce', required=True)
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    total = fields.Monetary(compute='_compute_total', string='Total dotation', store=True)
    line_ids = fields.One2many('ka.immo.dotation.ligne', 'dotation_id', string='Écritures générées (aperçu)')
    plan_ids = fields.Many2many('ka.immo.plan', string='Échéances traitées', copy=False)
    move_ids = fields.Many2many('account.move', string='Pièces générées', copy=False)
    trace = fields.Text(readonly=True)
    state = fields.Selection([('brouillon', 'À simuler'), ('simulee', 'Simulée'), ('comptabilisee', 'Comptabilisée')],
                             default='brouillon', string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        d = self.periode.strftime('%d/%m/%Y') if self.periode else ''
        return "%s — dotation de l'échéance du %s" % (self.name, d)

    @api.depends('line_ids.debit')
    def _compute_total(self):
        for d in self:
            d.total = sum(d.line_ids.mapped('debit'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = 'DOT-%s' % fields.Date.today().strftime('%Y-%m')
                vals['name'] += '-%s' % (self.search_count([]) + 1)
        return super().create(vals_list)

    def _echeances(self):
        self.ensure_one()
        return self.env['ka.immo.plan'].search([
            ('move_id', '=', False), ('date', '<=', fin_de_mois(self.periode)),
            ('immo_id.state', '=', 'en_service'), ('immo_id.famille_id', '!=', False)], order='date, id')

    def action_simuler(self):
        for d in self:
            d.line_ids.unlink()
            lignes = []
            for p in d._echeances():
                f = p.immo_id.famille_id
                lignes.append(Command.create({'compte': f.cpt_dotation, 'intitule': 'Dotation amortissements',
                                              'immo_id': p.immo_id.id, 'section': p.immo_id.analytic_id.code or '',
                                              'debit': p.dotation}))
                lignes.append(Command.create({'compte': f.cpt_amort, 'intitule': 'Amort. %s' % (f.name or '').lower(),
                                              'immo_id': p.immo_id.id, 'credit': p.dotation}))
            d.write({'line_ids': lignes, 'state': 'simulee', 'plan_ids': [Command.set(d._echeances().ids)]})

    def action_comptabiliser(self):
        """Une pièce équilibrée par échéance et par immobilisation, ventilée sur la section analytique."""
        for d in self:
            if d.state == 'comptabilisee':
                raise UserError(_('Ce traitement est déjà comptabilisé.'))
            journal = d.journal_id or self.env['account.journal'].search([('type', '=', 'general')], limit=1)
            if not journal:
                raise UserError(_("Aucun journal d'opérations diverses n'est configuré."))
            echeances = d._echeances()
            if not echeances:
                raise UserError(_('Aucune échéance à comptabiliser sur cette période.'))
            moves = self.env['account.move']
            for p in echeances:
                i, f = p.immo_id, p.immo_id.famille_id
                dist = {str(i.analytic_id.id): 100} if i.analytic_id else False
                move = self.env['account.move'].create({
                    'move_type': 'entry', 'journal_id': journal.id, 'date': d.date_piece,
                    'ref': '%s — %s' % (d.name, i.name), 'line_ids': [
                        Command.create({'account_id': compte(self.env, f.cpt_dotation).id, 'name': 'Dotation amortissements %s' % i.name,
                                        'debit': p.dotation, 'credit': 0.0, 'analytic_distribution': dist}),
                        Command.create({'account_id': compte(self.env, f.cpt_amort).id, 'name': 'Amort. %s %s' % ((f.name or '').lower(), i.name),
                                        'debit': 0.0, 'credit': p.dotation})]})
                move.action_post()
                p.move_id = move
                moves |= move
            d.write({'state': 'comptabilisee', 'move_ids': [Command.set(moves.ids)],
                     'trace': _('%s pièce(s) comptabilisée(s) pour %s FCFA.') % (len(moves), round(sum(echeances.mapped('dotation'))))})

    def action_ecritures(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Écritures', 'res_model': 'account.move',
                'view_mode': 'list,form', 'domain': [('id', 'in', self.move_ids.ids)]}

    def action_trace(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Trace', 'res_model': 'ka.immo.dotation', 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}


class KaImmoDotationLigne(models.Model):
    _name = 'ka.immo.dotation.ligne'
    _description = 'Ligne de dotation (aperçu)'
    _order = 'id'

    dotation_id = fields.Many2one('ka.immo.dotation', required=True, ondelete='cascade')
    compte = fields.Char(string='Compte')
    intitule = fields.Char(string='Intitulé')
    immo_id = fields.Many2one('ka.immo', string='Immobilisation')
    section = fields.Char(string='Section analytique')
    debit = fields.Float(string='Débit', digits=(14, 0))
    credit = fields.Float(string='Crédit', digits=(14, 0))
