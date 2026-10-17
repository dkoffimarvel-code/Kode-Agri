from odoo import _, api, fields, models


class AccountMove(models.Model):
    """Facture de vente export en devise (écran 7.1) : champs d'affichage et commande ouverte d'origine."""
    _inherit = 'account.move'

    ka_contrat_id = fields.Many2one('ka.contrat', string='Commande ouverte')
    ka_site_id = fields.Many2one('ka.site', string='Site de vente')
    ka_cours = fields.Char(compute='_compute_ka_facture', string='Cours')
    ka_devise_txt = fields.Char(compute='_compute_ka_facture', string='Devise')
    ka_montant_txt = fields.Char(compute='_compute_ka_facture', string='Montant')
    ka_statut_label = fields.Char(compute='_compute_ka_facture', string='Statut')
    ka_subtitle = fields.Char(compute='_compute_ka_facture')

    @api.depends('currency_id', 'amount_total', 'state', 'partner_id', 'name', 'move_type', 'invoice_date')
    def _compute_ka_facture(self):
        labels = {'draft': 'Provisoire', 'posted': 'Validée', 'cancel': 'Annulée'}
        for m in self:
            cur, comp = m.currency_id, m.company_id.currency_id
            rate = 1.0
            if cur and comp and cur != comp:
                rate = cur._get_conversion_rate(cur, comp, m.company_id, m.invoice_date or fields.Date.today())
            m.ka_cours = ('%s %s / %s' % ('{:,.0f}'.format(rate).replace(',', ' '), comp.symbol or comp.name, cur.name)) if cur != comp else ''
            m.ka_devise_txt = cur.name or ''
            m.ka_montant_txt = '%s %s' % ('{:,.0f}'.format(m.amount_total).replace(',', ' '), cur.name or '')
            m.ka_statut_label = labels.get(m.state, '')
            kind = 'vente export' if m.move_type == 'out_invoice' and m.partner_id.ka_cat_client == 'export' else 'vente'
            m.ka_subtitle = '%s — %s · %s' % (m.name if m.name and m.name != '/' else 'Brouillon', m.partner_id.name or '', kind)

    def action_valider_ka(self):
        self.filtered(lambda m: m.state == 'draft').action_post()

    def action_imprimer_ka(self):
        self.ensure_one()
        return self.env['ka.structure']._notif(_('Facture'), _('Facture envoyée à l\'impression.'))

    def action_reglement_ka(self):
        self.ensure_one()
        return self.action_register_payment()
