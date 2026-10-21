from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.kode_agri_production.models.common import ka_param


class KaRapprochement(models.Model):
    """Contrôle facture à trois niveaux commande / réception / facture avec tolérances (RG-8.1)."""
    _name = 'ka.rapprochement'
    _description = 'Contrôle facture fournisseur'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'id desc'

    name = fields.Char(string='N° contrôle', readonly=True, copy=False, default='Nouveau')
    move_id = fields.Many2one('account.move', string='Facture', required=True, domain=[('move_type', '=', 'in_invoice')])
    partner_id = fields.Many2one(related='move_id.partner_id', string='Fournisseur', store=True)
    date_facture = fields.Date(related='move_id.invoice_date', string='Date facture')
    echeance = fields.Char(compute='_compute_echeance', string='Échéance')
    commande_txt = fields.Char(compute='_compute_refs', string='Commande')
    reception_txt = fields.Char(compute='_compute_refs', string='Réception')
    line_ids = fields.One2many('ka.rapprochement.ligne', 'rap_id', string='Lignes')
    currency_id = fields.Many2one(related='move_id.currency_id')
    total_ht = fields.Monetary(compute='_compute_totaux', string='Total HT')
    ecart_txt = fields.Char(compute='_compute_totaux', string='Écart')
    controle = fields.Selection([('conforme', 'Conforme'), ('ecart', 'Écart hors tolérance')], compute='_compute_totaux',
                                string='Statut du contrôle')
    tol_qty = fields.Float(string='Tolérance quantité', default=lambda s: ka_param(s.env, 'tolerance_quantite', 0.0))
    tol_prix = fields.Float(string='Tolérance prix (%)', default=lambda s: ka_param(s.env, 'tolerance_prix', 2.0))
    state = fields.Selection([('a_controler', 'À contrôler'), ('rapprochee', 'Rapprochée'), ('attente', 'En attente de contrôle')],
                             default='a_controler', string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        rec = ' · réception %s' % self.reception_txt if self.reception_txt else ''
        return '%s — %s%s' % (self.move_id.name or 'Brouillon', self.partner_id.name or '', rec)

    @api.depends('move_id.invoice_payment_term_id')
    def _compute_echeance(self):
        for r in self:
            r.echeance = r.move_id.invoice_payment_term_id.name or ''

    @api.depends('move_id')
    def _compute_refs(self):
        for r in self:
            pos = r.move_id.invoice_line_ids.purchase_line_id.order_id
            pickings = pos.picking_ids
            r.commande_txt = ', '.join(pos.mapped('name'))
            r.reception_txt = ', '.join(pickings.mapped('name'))

    @api.depends('line_ids.ecart_qty', 'line_ids.ecart_prix', 'line_ids.montant', 'line_ids.hors_tolerance')
    def _compute_totaux(self):
        for r in self:
            r.total_ht = sum(r.line_ids.mapped('montant'))
            ecart = sum(abs(l.ecart_qty) for l in r.line_ids)
            r.ecart_txt = '%d' % ecart if ecart == int(ecart) else '%.1f' % ecart
            r.controle = 'ecart' if any(r.line_ids.mapped('hors_tolerance')) else 'conforme'

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create([dict(v, name=self.env['ir.sequence'].next_by_code('ka.rapprochement')) if v.get('name', 'Nouveau') == 'Nouveau' else v for v in vals_list])
        for r in recs:
            r._charger()
        return recs

    def _charger(self):
        """Une ligne par ligne de facture, rapprochée de la ligne de commande (quantités reçues et prix)."""
        for r in self:
            r.line_ids.unlink()
            lignes = []
            for l in r.move_id.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
                pol = l.purchase_line_id
                recu = pol.qty_received if pol else l.quantity
                lignes.append(Command.create({
                    'sequence': 1000 * (len(lignes) + 1), 'product_id': l.product_id.id, 'designation': l.name,
                    'recu': recu, 'facture': l.quantity, 'prix_net': l.price_unit,
                    'prix_commande': pol.price_unit if pol else l.price_unit}))
            r.line_ids = lignes

    def action_controle(self):
        self._charger()
        return True

    def action_attente(self):
        self.write({'state': 'attente'})

    def action_valider(self):
        """RG-8.1 : au-delà de la tolérance de prix ou de quantité, la facture reste en attente de contrôle ;
        sinon elle est comptabilisée et solde le compte des factures non parvenues."""
        for r in self:
            if r.controle == 'ecart':
                r.state = 'attente'
                raise UserError(_("Écart hors tolérance : la facture est mise en attente de contrôle (RG-8.1)."))
            if r.move_id.state == 'draft':
                r.move_id.action_post()
            r.state = 'rapprochee'


class KaRapprochementLigne(models.Model):
    _name = 'ka.rapprochement.ligne'
    _description = 'Ligne de contrôle facture'
    _order = 'sequence, id'

    rap_id = fields.Many2one('ka.rapprochement', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Ligne', default=1000)
    product_id = fields.Many2one('product.product', string='Article / service')
    designation = fields.Char()
    recu = fields.Float(string='Reçu', digits=(10, 0))
    facture = fields.Float(string='Facturé', digits=(10, 0))
    ecart_qty = fields.Float(compute='_compute_ecart', string='Écart', digits=(10, 0), store=True)
    prix_net = fields.Float(string='Prix net', digits=(12, 0))
    prix_commande = fields.Float(string='Prix commande', digits=(12, 0))
    ecart_prix = fields.Float(compute='_compute_ecart', string='Écart prix (%)', digits=(6, 2), store=True)
    montant = fields.Float(compute='_compute_ecart', string='Montant', digits=(14, 0), store=True)
    hors_tolerance = fields.Boolean(compute='_compute_ecart', store=True)

    @api.depends('recu', 'facture', 'prix_net', 'prix_commande', 'rap_id.tol_qty', 'rap_id.tol_prix')
    def _compute_ecart(self):
        for l in self:
            l.ecart_qty = l.facture - l.recu
            l.ecart_prix = ((l.prix_net - l.prix_commande) / l.prix_commande * 100.0) if l.prix_commande else 0.0
            l.montant = l.facture * l.prix_net
            l.hors_tolerance = abs(l.ecart_qty) > l.rap_id.tol_qty or abs(l.ecart_prix) > l.rap_id.tol_prix
