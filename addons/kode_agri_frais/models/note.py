from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

COMPTE_PERSONNEL = '421000'


class KaFraisNote(models.Model):
    """Note de frais d'un collaborateur : saisie → approbation → comptabilisation → remboursement."""
    _name = 'ka.frais.note'
    _description = 'Note de frais'
    _inherit = ['ka.document', 'mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(string='N° note', readonly=True, copy=False, default='Nouveau')
    intitule = fields.Char(string='Intitulé', default='Tournée collecte')
    salarie_id = fields.Many2one('res.partner', string='Salarié', required=True, domain=[('ka_salarie', '=', True)])
    date_debut = fields.Date(string='Période', required=True)
    date_fin = fields.Date(required=True)
    analytic_id = fields.Many2one('account.analytic.account', string='Section analytique', required=True)
    analytic_code = fields.Char(related='analytic_id.code', string='Section analytique')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    line_ids = fields.One2many('ka.frais.ligne', 'note_id', string='Dépenses')
    total = fields.Monetary(compute='_compute_total', string='Total', store=True)
    nb_justificatifs = fields.Integer(compute='_compute_justificatifs')
    justificatifs_txt = fields.Char(compute='_compute_justificatifs', string='Documents attachés')
    plafonds = fields.Selection([('respectes', 'Respectés'), ('depasses', 'Dépassés')], compute='_compute_plafonds',
                                string='Plafonds', store=True)
    refacturable = fields.Selection([('non', 'Non'), ('oui', 'Oui')], default='non', string='Refacturable')
    approbateur = fields.Char(string='Approbateur', default='Responsable collecte')
    move_id = fields.Many2one('account.move', string='Pièce comptable', readonly=True, copy=False)
    piece_ref = fields.Char(string='Pièce', readonly=True, copy=False)
    date_compta = fields.Date(string='Date comptable', readonly=True, copy=False)
    piece_ids = fields.One2many('ka.frais.piece', 'note_id', string='Pièce générée — journal NDF')
    reglement_id = fields.Many2one('ka.frais.reglement', readonly=True, copy=False)
    state = fields.Selection([('saisie', 'Saisie'), ('a_approuver', 'À approuver'), ('approuvee', 'Approuvée'),
                              ('comptabilisee', 'Comptabilisée'), ('remboursee', 'Remboursée'),
                              ('refusee', 'Refusée')], default='saisie', string='Statut', tracking=True)
    badge_label = fields.Char(compute='_compute_badge')

    def _ka_subtitle(self):
        self.ensure_one()
        if self.state == 'a_approuver':
            return '%s — approbateur : %s' % (self.name, (self.approbateur or '').lower())
        if self.state in ('comptabilisee', 'remboursee') and self.piece_ref:
            d = self.date_compta.strftime('%d/%m/%Y') if self.date_compta else ''
            return '%s — pièce %s du %s' % (self.name, self.piece_ref, d)
        mois = self.date_debut.strftime('%m/%Y') if self.date_debut else ''
        return '%s — %s · %s' % (self.name, self.intitule or '', mois)

    @api.depends('state')
    def _compute_badge(self):
        for n in self:
            n.badge_label = dict(self._fields['state'].selection)[n.state]

    @api.depends('line_ids.montant')
    def _compute_total(self):
        for n in self:
            n.total = sum(n.line_ids.mapped('montant'))

    @api.depends('line_ids.depassement')
    def _compute_plafonds(self):
        for n in self:
            n.plafonds = 'depasses' if any(n.line_ids.mapped('depassement')) else 'respectes'

    def _compute_justificatifs(self):
        for n in self:
            n.nb_justificatifs = self.env['ir.attachment'].search_count(
                [('res_model', '=', 'ka.frais.note'), ('res_id', '=', n.id)]) if n.id else 0
            nb = n.nb_justificatifs
            n.justificatifs_txt = '%s justificatif%s' % (nb, 's' if nb > 1 else '')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.frais.note')
        return super().create(vals_list)

    # ---- cycle (§ 6.1) ----------------------------------------------------------------------------------
    def action_joindre(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Joindre un justificatif', 'res_model': 'ir.attachment',
                'view_mode': 'form', 'target': 'new',
                'context': {'default_res_model': 'ka.frais.note', 'default_res_id': self.id}}

    def action_soumettre(self):
        for n in self:
            if n.state != 'saisie':
                raise UserError(_('Seule une note en saisie peut être soumise.'))
            if not n.line_ids:
                raise UserError(_('La note ne contient aucune dépense.'))
            sans = n.line_ids.filtered(lambda l: not l.justificatif)
            if sans:
                raise UserError(_('Justificatif manquant pour : %s') % ', '.join(sans.mapped('description')))
            if n.plafonds == 'depasses':   # plafonds par catégorie : contrôle spécifique léger
                raise UserError(_('Plafond dépassé : %s') % ', '.join(
                    '%s (%s > %s)' % (l.categorie_id.code, l.montant, l.plafond) for l in n.line_ids if l.depassement))
            n.state = 'a_approuver'
            n.activity_schedule('mail.mail_activity_data_todo', summary=_('Note de frais %s à approuver') % n.name,
                                user_id=self.env.user.id)

    def action_approuver(self):
        self.filtered(lambda n: n.state == 'a_approuver').write({'state': 'approuvee'})

    def action_refuser(self):
        self.filtered(lambda n: n.state == 'a_approuver').write({'state': 'refusee'})

    def _compte(self, code):
        acc = self.env['account.account'].search([('code', '=', code)], limit=1)
        if not acc:
            raise UserError(_("Le compte %s est introuvable dans le plan comptable.") % code)
        return acc

    def action_comptabiliser(self):
        """Génère la pièce du journal NDF : charge ventilée par code frais et section analytique,
        contrepartie au compte du salarié (421000)."""
        for n in self:
            if n.state != 'approuvee':
                raise UserError(_("La note doit être approuvée avant d'être comptabilisée."))
            journal = self.env['account.journal'].search([('code', '=', 'NDF'), ('type', '=', 'general')], limit=1) \
                or self.env['account.journal'].search([('type', '=', 'general')], limit=1)
            date = fields.Date.context_today(n)
            lignes, pieces = [], []
            for l in n.line_ids:
                acc = n._compte(l.categorie_id.compte_code)
                lib = '%s — %s %s' % (l.categorie_id.name, l.description, l.date.strftime('%d/%m') if l.date else '')
                lignes.append(Command.create({'account_id': acc.id, 'name': lib, 'debit': l.montant, 'credit': 0.0,
                                              'partner_id': n.salarie_id.id,
                                              'analytic_distribution': {str(n.analytic_id.id): 100}}))
                pieces.append(Command.create({'compte': acc.code, 'intitule': lib, 'section': n.analytic_code or '',
                                              'debit': l.montant}))
            perso = n._compte(COMPTE_PERSONNEL)
            lib_perso = 'Personnel — notes de frais à payer (%s)' % (n.salarie_id.ka_matricule or n.salarie_id.name)
            lignes.append(Command.create({'account_id': perso.id, 'name': lib_perso, 'debit': 0.0, 'credit': n.total,
                                          'partner_id': n.salarie_id.id}))
            pieces.append(Command.create({'compte': perso.code, 'intitule': lib_perso, 'credit': n.total}))
            move = self.env['account.move'].create({'move_type': 'entry', 'journal_id': journal.id, 'date': date,
                                                    'ref': n.name, 'line_ids': lignes})
            move.action_post()
            n.piece_ids.unlink()
            n.write({'move_id': move.id, 'piece_ref': 'NDF-%s-%s' % (date.year, n.name.split('-')[-1]),
                     'date_compta': date, 'state': 'comptabilisee', 'piece_ids': pieces})

    def action_voir_piece(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_("Aucune pièce n'a encore été générée."))
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': self.move_id.id,
                'view_mode': 'form'}

    def action_proposer_reglement(self):
        """Crée la proposition de remboursement du salarié (virement)."""
        self.ensure_one()
        if self.state != 'comptabilisee':
            raise UserError(_("Comptabilisez la note avant de proposer son règlement."))
        reg = self.env['ka.frais.reglement'].create({'note_id': self.id, 'salarie_id': self.salarie_id.id,
                                                     'montant': self.total})
        self.reglement_id = reg
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.frais.reglement', 'res_id': reg.id,
                'view_mode': 'form'}


class KaFraisLigne(models.Model):
    _name = 'ka.frais.ligne'
    _description = 'Dépense de note de frais'
    _order = 'date, id'

    note_id = fields.Many2one('ka.frais.note', required=True, ondelete='cascade')
    date = fields.Date(required=True, default=fields.Date.context_today)
    categorie_id = fields.Many2one('ka.frais.categorie', string='Code frais', required=True)
    description = fields.Char(string='Description', required=True)
    justificatif = fields.Boolean(string='Justificatif')
    currency_id = fields.Many2one(related='note_id.currency_id')
    plafond = fields.Monetary(related='categorie_id.plafond', string='Plafond')
    montant = fields.Monetary(string='Montant', required=True)
    depassement = fields.Boolean(compute='_compute_depassement', store=True)

    @api.depends('montant', 'categorie_id.plafond')
    def _compute_depassement(self):
        for l in self:
            l.depassement = bool(l.categorie_id.plafond) and l.montant > l.categorie_id.plafond


class KaFraisPiece(models.Model):
    _name = 'ka.frais.piece'
    _description = 'Ligne de la pièce générée'
    _order = 'id'

    note_id = fields.Many2one('ka.frais.note', ondelete='cascade')
    reglement_id = fields.Many2one('ka.frais.reglement', ondelete='cascade')
    compte = fields.Char(string='Compte')
    intitule = fields.Char(string='Intitulé')
    section = fields.Char(string='Section')
    debit = fields.Float(string='Débit', digits=(12, 0))
    credit = fields.Float(string='Crédit', digits=(12, 0))
