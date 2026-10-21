from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

TYPES = [
    ('cca', 'CCA — Charge constatée d\'avance'), ('pca', 'PCA — Produit constaté d\'avance'),
    ('cap', 'CAP — Charge à payer'), ('par', 'PAR — Produit à recevoir'),
    ('prov_risque', 'Provision pour risques et charges'), ('prov_stock', 'Provision pour dépréciation des stocks'),
    ('prov_client', 'Provision pour créances douteuses'),
]
# Comptes indicatifs (SYSCOHADA) : à caler sur le plan comptable de l'entreprise ; modifiables sur la fiche.
DEFAUT = {'cca': ('476', None), 'pca': (None, '477'), 'cap': (None, '4081'), 'par': ('4181', None)}


class KaRegul(models.Model):
    """Écriture de régularisation de fin de période avec extourne automatique à l'ouverture suivante (RG-8.5)."""
    _name = 'ka.regul'
    _description = "Régularisation d'arrêté"
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° régularisation', readonly=True, copy=False, default='Nouveau')
    type = fields.Selection(TYPES, string='Nature', required=True, default='cca')
    libelle = fields.Char(string='Libellé', required=True)
    date_cloture = fields.Date(string='Date de clôture', required=True)
    date_extourne = fields.Date(compute='_compute_extourne', string="Date d'extourne", store=True)
    journal_id = fields.Many2one('account.journal', string='Journal', domain=[('type', '=', 'general')])
    compte_charge_id = fields.Many2one('account.account', string='Compte de charge ou de produit', required=True)
    compte_regul_id = fields.Many2one('account.account', string='Compte de régularisation', required=True)
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    montant = fields.Monetary(string='Montant', required=True)
    extourne = fields.Boolean(string='Extourne automatique', compute='_compute_extourne', store=True)
    move_id = fields.Many2one('account.move', string='Pièce de clôture', readonly=True, copy=False)
    move_extourne_id = fields.Many2one('account.move', string="Pièce d'extourne", readonly=True, copy=False)
    state = fields.Selection([('brouillon', 'Brouillon'), ('comptabilisee', 'Comptabilisée'), ('extournee', 'Extournée')],
                             default='brouillon', string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — %s' % (self.name, dict(self._fields['type'].selection)[self.type])

    @api.depends('type', 'date_cloture')
    def _compute_extourne(self):
        for r in self:
            r.extourne = r.type in ('cca', 'pca', 'cap', 'par')           # les provisions se reprennent, elles ne s'extournent pas
            r.date_extourne = (r.date_cloture + timedelta(days=1)) if (r.extourne and r.date_cloture) else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.regul')
        return super().create(vals_list)

    def _sens(self):
        """(compte débité, compte crédité) selon la nature."""
        self.ensure_one()
        c, r = self.compte_charge_id, self.compte_regul_id
        return {'cca': (r, c), 'pca': (c, r), 'cap': (c, r), 'par': (r, c),
                'prov_risque': (c, r), 'prov_stock': (c, r), 'prov_client': (c, r)}[self.type]

    def _creer_piece(self, date, inverse=False, suffixe=''):
        self.ensure_one()
        deb, cred = self._sens()
        if inverse:
            deb, cred = cred, deb
        journal = self.journal_id or self.env['account.journal'].search([('type', '=', 'general')], limit=1)
        if not journal:
            raise UserError(_("Aucun journal d'opérations diverses n'est configuré."))
        move = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': journal.id, 'date': date, 'ref': '%s — %s%s' % (self.name, self.libelle, suffixe),
            'line_ids': [Command.create({'account_id': deb.id, 'name': self.libelle, 'debit': self.montant, 'credit': 0.0}),
                         Command.create({'account_id': cred.id, 'name': self.libelle, 'debit': 0.0, 'credit': self.montant})]})
        move.action_post()
        return move

    def action_comptabiliser(self):
        for r in self:
            if r.state != 'brouillon':
                raise UserError(_('Cette régularisation est déjà comptabilisée.'))
            r.move_id = r._creer_piece(r.date_cloture)
            r.state = 'comptabilisee'

    def action_extourner(self):
        """Contre-passation à l'ouverture suivante : même montant, sens inverse, au lendemain de la clôture (RG-8.5)."""
        for r in self:
            if not r.extourne:
                raise UserError(_("Une provision se reprend (reprise de provision) ; elle ne s'extourne pas."))
            if r.state != 'comptabilisee':
                raise UserError(_("Comptabilisez la régularisation avant de l'extourner."))
            r.move_extourne_id = r._creer_piece(r.date_extourne, inverse=True, suffixe=' (extourne)')
            r.state = 'extournee'

    @api.model
    def cron_extourner(self):
        """Action planifiée : extourne les régularisations dont la date d'ouverture est atteinte."""
        today = fields.Date.context_today(self)
        for r in self.search([('state', '=', 'comptabilisee'), ('extourne', '=', True), ('date_extourne', '<=', today)]):
            r.action_extourner()

    def action_reprise(self):
        """Reprise de provision (risque levé, recouvrement, stock repris) : écriture inverse, constatée en produit."""
        for r in self:
            if r.extourne or r.state != 'comptabilisee':
                raise UserError(_('La reprise ne concerne que les provisions comptabilisées.'))
            r.move_extourne_id = r._creer_piece(fields.Date.context_today(r), inverse=True, suffixe=' (reprise)')
            r.state = 'extournee'

    def action_ecritures(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Écritures', 'res_model': 'account.move',
                'view_mode': 'list,form', 'domain': [('id', 'in', (self.move_id | self.move_extourne_id).ids)]}
