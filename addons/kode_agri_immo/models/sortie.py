from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .dotation import compte
from .immo import fin_de_mois


class KaImmoSortie(models.Model):
    """Cession ou mise au rebut : sortie du parc, arrêt des dotations, VNC et plus ou moins-value (écran 3.3)."""
    _name = 'ka.immo.sortie'
    _description = "Sortie d'immobilisation"
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° sortie', readonly=True, copy=False, default='Nouveau')
    immo_id = fields.Many2one('ka.immo', string='Immobilisation', required=True, domain=[('state', '=', 'en_service')])
    type = fields.Selection([('cession', 'Cession'), ('rebut', 'Mise au rebut')], string='Type de sortie', required=True, default='cession')
    date = fields.Date(string='Date de sortie', required=True, default=fields.Date.context_today)
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    prix = fields.Monetary(string='Prix de cession')
    vnc = fields.Monetary(compute='_compute_resultat', string='VNC résiduelle')
    plus_value = fields.Monetary(compute='_compute_resultat', string='Plus ou moins-value')
    plus_value_txt = fields.Char(compute='_compute_resultat')
    partner_id = fields.Many2one('res.partner', string='Acquéreur')
    move_id = fields.Many2one('account.move', readonly=True, copy=False)
    state = fields.Selection([('brouillon', 'Brouillon'), ('a_valider', 'À approuver'), ('approuvee', 'Approuvée'),
                              ('validee', 'Comptabilisée')], default='a_valider', string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s (%s)' % (self.immo_id.intitule or '', self.immo_id.name or '')

    @api.depends('name', 'immo_id.intitule')
    def _compute_display_name(self):
        for s in self:
            s.display_name = '%s — %s' % (s.name, s.immo_id.intitule) if s.immo_id.intitule else (s.name or '')

    def action_approuver(self):
        """Approbation de la cession : contrôle de l'immobilisation, du prix et de la VNC avant comptabilisation."""
        for s in self:
            if s.state not in ('brouillon', 'a_valider'):
                raise UserError(_('Cette sortie est déjà approuvée.'))
            if s.immo_id.state != 'en_service':
                raise UserError(_("Seule une immobilisation en service peut être cédée."))
            if s.type == 'cession' and not s.prix:
                raise UserError(_('Indiquez le prix de cession.'))
            s.state = 'approuvee'

    def action_ecritures(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Écritures', 'res_model': 'account.move',
                'view_mode': 'list,form', 'domain': [('id', 'in', self.move_id.ids)]}

    def _vnc_a(self, immo, date):
        """VNC à la date de sortie : valeur − dotations échues jusqu'à la date (comptabilisées ou non)."""
        cumul = sum(immo.plan_ids.filtered(lambda p: p.date <= date).mapped('dotation'))
        return immo.valeur - cumul

    @api.depends('immo_id', 'date', 'prix', 'type')
    def _compute_resultat(self):
        for s in self:
            s.vnc = s._vnc_a(s.immo_id, s.date) if s.immo_id and s.date else 0.0
            s.plus_value = (s.prix if s.type == 'cession' else 0.0) - s.vnc
            s.plus_value_txt = ('%s%s FCFA' % ('+' if s.plus_value >= 0 else '−', '{:,.0f}'.format(abs(s.plus_value)).replace(',', ' ')))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.immo.sortie')
        return super().create(vals_list)

    def action_simuler(self):
        self.ensure_one()
        return self.env['ka.structure']._notif(_('Résultat de cession'), _('VNC %s FCFA — plus ou moins-value %s.') % (
            '{:,.0f}'.format(self.vnc).replace(',', ' '), self.plus_value_txt))

    def action_valider(self):
        """Comptabilise la sortie : reprise de l'amortissement cumulé, VNC en valeur comptable de cession (81),
        produit de cession (82) ; interrompt les dotations ultérieures."""
        for s in self:
            if s.state not in ('brouillon', 'a_valider', 'approuvee'):
                continue
            i, f = s.immo_id, s.immo_id.famille_id
            journal = self.env['account.journal'].search([('type', '=', 'general')], limit=1)
            if not journal:
                raise UserError(_("Aucun journal d'opérations diverses n'est configuré."))
            echues = i.plan_ids.filtered(lambda p: p.date <= s.date)
            non_compta = echues.filtered(lambda p: not p.move_id)
            cumul = sum(echues.mapped('dotation'))
            dist = {str(i.analytic_id.id): 100} if i.analytic_id else False
            lignes = []
            if non_compta:   # dotations échues non encore passées : comptabilisées avec la sortie
                lignes += [Command.create({'account_id': compte(self.env, f.cpt_dotation).id, 'name': 'Dotation jusqu\'à la sortie %s' % i.name,
                                           'debit': sum(non_compta.mapped('dotation')), 'credit': 0.0, 'analytic_distribution': dist})]
            lignes += [
                Command.create({'account_id': compte(self.env, f.cpt_amort).id, 'name': 'Reprise amortissements %s' % i.name,
                                'debit': cumul, 'credit': 0.0}),
                Command.create({'account_id': compte(self.env, '811').id, 'name': 'VNC des immobilisations cédées %s' % i.name,
                                'debit': s.vnc, 'credit': 0.0}),
                Command.create({'account_id': compte(self.env, f.cpt_immo).id, 'name': 'Sortie du parc %s' % i.name,
                                'debit': 0.0, 'credit': i.valeur})]
            if non_compta:   # contrepartie de la dotation rattrapée sur l'amortissement cumulé
                lignes += [Command.create({'account_id': compte(self.env, f.cpt_amort).id, 'name': 'Amortissements rattrapés %s' % i.name,
                                           'debit': 0.0, 'credit': sum(non_compta.mapped('dotation'))})]
            if s.type == 'cession' and s.prix:
                tiers = s.partner_id.property_account_receivable_id or compte(self.env, '4851')
                lignes += [Command.create({'account_id': tiers.id, 'partner_id': s.partner_id.id, 'name': 'Cession %s' % i.name,
                                           'debit': s.prix, 'credit': 0.0}),
                           Command.create({'account_id': compte(self.env, '821').id, 'name': 'Produit de cession %s' % i.name,
                                           'debit': 0.0, 'credit': s.prix})]
            lignes = [l for l in lignes if l[2].get('debit') or l[2].get('credit')]
            move = self.env['account.move'].create({'move_type': 'entry', 'journal_id': journal.id, 'date': s.date,
                                                    'ref': '%s — %s' % (s.name, i.name), 'line_ids': lignes})
            move.action_post()
            non_compta.write({'move_id': move.id})
            i.plan_ids.filtered(lambda p: p.date > s.date).unlink()   # arrêt des dotations
            i.state = 'sortie'
            s.write({'move_id': move.id, 'state': 'validee'})
