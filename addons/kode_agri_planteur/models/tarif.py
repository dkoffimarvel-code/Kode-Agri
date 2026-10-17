from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.tools import date_utils


class KaTarif(models.Model):
    _name = 'ka.tarif'
    _description = "Tarif d'achat — prix Apromac"
    _inherit = ['ka.document']
    _rec_name = 'code'
    _order = 'date_start desc'

    code = fields.Char(string='Code tarif', required=True, default='APROMAC', readonly=True)
    product_id = fields.Many2one('product.product', string='Article')
    date_start = fields.Date(string='Date début validité', required=True)
    date_end = fields.Date(string='Date fin validité', required=True)
    critere = fields.Selection([('lieu', 'Lieu de livraison')], string='Critère', default='lieu')
    uom_label = fields.Char(string='Unité', default='KG (humide)')
    currency_id = fields.Many2one('res.currency', string='Devise',
                                  default=lambda s: s.env.ref('base.XOF', raise_if_not_found=False))
    bareme_ids = fields.One2many('ka.tarif.bareme', 'tarif_id', string='Barèmes du mois')
    state = fields.Selection([('actif', 'Actif'), ('ferme', 'Fermé')], default='actif', string='Statut')

    def _ka_subtitle(self):
        self.ensure_one()
        if not self.date_start:
            return 'Code tarif APROMAC'
        mois = self.date_start.strftime('%m/%Y')
        return 'Code tarif %s — période %s' % (self.code, mois)

    def action_dupliquer_mois(self):
        self.ensure_one()
        start = self.date_end + relativedelta(days=1)
        end = date_utils.end_of(start, 'month')
        new = self.copy({'date_start': start, 'date_end': end, 'state': 'actif'})
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.tarif',
                'res_id': new.id, 'view_mode': 'form'}

    def action_fermer(self):
        self.write({'state': 'ferme'})

    @api.model
    def prix_pour(self, lieu, date):
        """Barème (FCFA/kg humide) applicable au lieu de livraison et au mois de pesée (RG prix Apromac)."""
        bareme = self.env['ka.tarif.bareme'].search([
            ('lieu', '=', lieu), ('tarif_id.date_start', '<=', date),
            ('tarif_id.date_end', '>=', date), ('tarif_id.state', '=', 'actif')], limit=1)
        return bareme.prix_kg if bareme else 0.0


class KaTarifBareme(models.Model):
    _name = 'ka.tarif.bareme'
    _description = 'Barème Apromac'

    tarif_id = fields.Many2one('ka.tarif', required=True, ondelete='cascade')
    name = fields.Char(string='Barème', required=True)
    lieu = fields.Selection([('usine', "Pont de l'usine"), ('bord_champ', 'Ponts de proximité')],
                            string='Lieu de livraison', required=True)
    lieu_label = fields.Char(compute='_compute_lieu_label', string='Lieu de livraison')
    currency_id = fields.Many2one(related='tarif_id.currency_id')
    prix_kg = fields.Monetary(string='Prix au kg humide', currency_field='currency_id')

    @api.depends('lieu')
    def _compute_lieu_label(self):
        labels = dict(self._fields['lieu'].selection)
        for rec in self:
            rec.lieu_label = labels.get(rec.lieu, '')

    @api.depends('name', 'prix_kg')
    def _compute_display_name(self):
        for b in self:
            b.display_name = '%s — %s FCFA/kg' % (b.name or '', int(b.prix_kg))
