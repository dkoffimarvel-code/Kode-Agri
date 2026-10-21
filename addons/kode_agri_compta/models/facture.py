from odoo import _, api, fields, models


class AccountMove(models.Model):
    """Facture de vente export en devise (écran 8.1) : champs d'affichage et commande ouverte d'origine."""
    _inherit = 'account.move'

    ka_contrat_id = fields.Many2one('ka.contrat', string='Commande ouverte')
    ka_site_id = fields.Many2one('ka.site', string='Site de vente')
    ka_cours = fields.Char(compute='_compute_ka_facture', string='Cours')
    ka_devise_txt = fields.Char(compute='_compute_ka_facture', string='Devise')
    ka_montant_txt = fields.Char(compute='_compute_ka_facture', string='Montant')
    ka_statut_label = fields.Char(compute='_compute_ka_facture', string='Statut')
    ka_subtitle = fields.Char(compute='_compute_ka_facture')
    # barre d'état de l'écran 8.1 : Brouillon › Comptabilisée › Payée (état de la pièce et état du paiement)
    ka_etape = fields.Selection([('brouillon', 'Brouillon'), ('comptabilisee', 'Comptabilisée'), ('payee', 'Payée'), ('annulee', 'Annulée')],
                                compute='_compute_ka_etape', string='Étape')

    @api.depends('state', 'payment_state')
    def _compute_ka_etape(self):
        for m in self:
            if m.state == 'cancel':
                m.ka_etape = 'annulee'
            elif m.state == 'draft':
                m.ka_etape = 'brouillon'
            else:
                m.ka_etape = 'payee' if m.payment_state in ('paid', 'in_payment', 'reversed') else 'comptabilisee'

    @api.depends('currency_id', 'amount_total', 'state', 'partner_id', 'name', 'move_type', 'invoice_date')
    def _compute_ka_facture(self):
        labels = {'draft': 'Provisoire', 'posted': 'Validée', 'cancel': 'Annulée'}
        for m in self:
            cur, comp = m.currency_id, m.company_id.currency_id
            rate = 1.0
            if cur and comp and cur != comp:
                rate = cur._get_conversion_rate(cur, comp, m.company_id, m.invoice_date or fields.Date.today())
            unite = 'FCFA' if comp.name in ('XOF', 'XAF') else (comp.name or '')
            m.ka_cours = ('%s %s/%s' % ('{:,.0f}'.format(rate).replace(',', ' '), unite, cur.name)) if cur != comp else ''
            m.ka_devise_txt = cur.name or ''
            m.ka_montant_txt = '{:,.0f}'.format(m.amount_total).replace(',', ' ')
            m.ka_statut_label = labels.get(m.state, '')
            if m.move_type in ('in_invoice', 'in_refund'):
                kind = 'Facture fournisseur'
            else:
                kind = 'Vente export' if m.partner_id.ka_cat_client == 'export' else 'Vente'
            m.ka_subtitle = '%s · %s (%s)' % (m.partner_id.name or '', kind, m.ka_statut_label.lower() or 'provisoire')

    def action_valider_ka(self):
        self.filtered(lambda m: m.state == 'draft').action_post()

    def action_imprimer_ka(self):
        self.ensure_one()
        return self.env['ka.structure']._notif(_('Facture'), _('Facture envoyée à l\'impression.'))

    def action_reglement_ka(self):
        self.ensure_one()
        return self.action_register_payment()

    def action_ka_ouvrir_devise(self):
        """Carte « Devise » : fiche de la devise et de ses cours."""
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Devise', 'res_model': 'res.currency', 'res_id': self.currency_id.id,
                'view_mode': 'form'}

    def action_ka_ouvrir_ecritures(self):
        """Carte « Montant » : écritures comptables de la facture."""
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Écritures', 'res_model': 'account.move.line', 'view_mode': 'list',
                'domain': [('move_id', '=', self.id)]}
