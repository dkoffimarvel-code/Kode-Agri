from odoo import Command, api, fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    ka_immobilisable = fields.Boolean(string='Immobilisable')
    ka_famille_id = fields.Many2one('ka.immo.famille', string="Famille d'immobilisation")
    ka_immo_ids = fields.One2many('ka.immo', 'move_line_id', string='Immobilisations')
    ka_immo_txt = fields.Char(compute='_compute_ka_immo_txt', string='Immobilisation')

    def _compute_ka_immo_txt(self):
        for l in self:
            l.ka_immo_txt = ', '.join(l.ka_immo_ids.mapped('name'))


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        for move in posted.filtered(lambda m: m.move_type == 'in_invoice'):
            move._ka_creer_immobilisations()
        return posted

    def _ka_creer_immobilisations(self):
        """À la validation d'une facture fournisseur, chaque ligne immobilisable (cochée, ou imputée sur le compte
        d'immobilisation d'une famille à création automatique) génère une immobilisation « à confirmer »."""
        Famille = self.env['ka.immo.famille']
        for line in self.invoice_line_ids.filtered(lambda l: l.display_type == 'product' and not l.ka_immo_ids):
            famille = line.ka_famille_id
            if not famille and line.account_id:
                famille = Famille.search([('cpt_immo', '=', line.account_id.code), ('creation_facture', '=', True)], limit=1)
            if not (famille and (line.ka_immobilisable or line.account_id.code == famille.cpt_immo)):
                continue
            self.env['ka.immo'].create({
                'intitule': line.name or line.product_id.name, 'famille_id': famille.id, 'methode': famille.methode,
                'duree': famille.duree, 'valeur': line.price_subtotal, 'date_service': self.invoice_date or self.date,
                'partner_id': self.partner_id.id, 'move_id': self.id, 'move_line_id': line.id,
                'ligne_facture': line.name, 'state': 'a_confirmer'})
