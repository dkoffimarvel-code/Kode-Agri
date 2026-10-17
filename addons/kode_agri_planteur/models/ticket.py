import base64
import csv
import io
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class KaTicketImport(models.Model):
    _name = 'ka.ticket.import'
    _description = "Lot d'import de tickets de pesée"
    _inherit = ['ka.document']
    _order = 'date desc, id desc'

    name = fields.Char(string="Lot d'import", required=True, copy=False, default='Nouveau')
    date = fields.Date(string="Date d'import", default=fields.Date.context_today)
    source = fields.Char(string='Fichier pont-bascule', default='SIPIC')
    file = fields.Binary(string='Fichier CSV (modèle YTKT)')
    filename = fields.Char()
    state = fields.Selection([('importe', 'Importé'), ('controle', 'Contrôlé'), ('valide', 'Validé (historisé)')],
                             default='importe', string='Statut')
    ticket_ids = fields.One2many('ka.ticket', 'import_id', string='Tickets')
    nb_tickets = fields.Integer(compute='_compute_totaux', string='Tickets')
    poids_t = fields.Float(compute='_compute_totaux', string='Poids net humide (t)', digits=(8, 1))

    @api.depends('ticket_ids.poids_net')
    def _compute_totaux(self):
        for rec in self:
            rec.nb_tickets = len(rec.ticket_ids)
            rec.poids_t = sum(rec.ticket_ids.mapped('poids_net')) / 1000.0

    def _ka_subtitle(self):
        self.ensure_one()
        d = self.date.strftime('%d/%m/%Y') if self.date else ''
        return "Lot d'import du %s — fichier pont-bascule %s" % (d, self.source or '')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.ticket.import')
        return super().create(vals_list)

    # ---- Import : modèle YTKT (CodeFournisseur, N_Ticket, DatePesee, Article, Poids N, Site, N_Lot, EUDR)
    def action_importer(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_('Sélectionnez le fichier CSV du pont-bascule avant de lancer l\'import.'))
        raw = base64.b64decode(self.file).decode('utf-8-sig')
        dialect = csv.Sniffer().sniff(raw[:2048], delimiters=';,\t')
        rows = list(csv.DictReader(io.StringIO(raw), dialect=dialect))
        Partner, Product = self.env['res.partner'], self.env['product.product']
        vals = []
        for row in rows:
            code = (row.get('CodeFournisseur') or '').strip()
            partner = Partner.search(['|', ('ka_code', '=', code), ('ref', '=', code)], limit=1)
            product = Product.search([('default_code', '=', (row.get('Article') or 'FDT-HEVEA').strip())], limit=1)
            date = datetime.strptime(row['DatePesee'].strip(), '%d/%m/%Y').date()
            vals.append({
                'import_id': self.id, 'name': row['N_Ticket'].strip(), 'date_pesee': date,
                'partner_code': code, 'partner_id': partner.id, 'product_id': product.id,
                'poids_net': float(str(row['Poids N']).replace(' ', '').replace(',', '.')),
                'site': (row.get('Site') or self.source or '').strip(),
                'lot_name': (row.get('N_Lot') or '').strip(),
                'parcelle_ref': (row.get('EUDR') or '').strip(),
            })
        self.ticket_ids.unlink()
        self.env['ka.ticket'].create(vals)
        self.state = 'importe'

    def action_supprimer_reimporter(self):
        self.ensure_one()
        if any(t.state == 'valide' for t in self.ticket_ids):
            raise UserError(_('Un ticket validé est figé (RG-1.6) : suppression impossible.'))
        self.ticket_ids.unlink()
        self.state = 'importe'

    def action_verifier(self):
        for rec in self:
            rec.ticket_ids._verifier()
            if rec.ticket_ids and all(t.state == 'controle' for t in rec.ticket_ids):
                rec.state = 'controle'

    def action_valider(self):
        self.ensure_one()
        if self.state != 'controle':
            raise UserError(_("Vérifiez les tickets avant de valider : tous doivent être au statut « Contrôlé »."))
        self.ticket_ids._generer_commandes()
        self.state = 'valide'

    def action_open_commandes(self):
        return {'type': 'ir.actions.act_window', 'name': "Commandes d'achat générées",
                'res_model': 'purchase.order', 'view_mode': 'tree,form',
                'domain': [('id', 'in', self.ticket_ids.purchase_id.ids)]}


class KaTicket(models.Model):
    _name = 'ka.ticket'
    _description = 'Ticket de pesée'
    _order = 'date_pesee, name'

    import_id = fields.Many2one('ka.ticket.import', ondelete='cascade')
    name = fields.Char(string='N° ticket', required=True)
    date_pesee = fields.Date(string='Date pesée', required=True)
    partner_code = fields.Char(string='Code fournisseur')
    partner_id = fields.Many2one('res.partner', string='Fournisseur')
    product_id = fields.Many2one('product.product', string='Article')
    poids_net = fields.Float(string='Poids net (kg)', digits=(10, 0))
    site = fields.Char(string='Site')
    lieu = fields.Selection([('usine', "Pont de l'usine"), ('bord_champ', 'Ponts de proximité')],
                            string='Lieu de livraison', default='usine')
    lot_name = fields.Char(string='Lot')
    parcelle_ref = fields.Char(string='Parcelle EUDR')
    state = fields.Selection([('importe', 'Importé'), ('a_controler', 'À contrôler'),
                              ('controle', 'Contrôlé'), ('valide', 'Validé')], default='a_controler',
                             string='Statut')
    purchase_id = fields.Many2one('purchase.order', string="Commande d'achat", readonly=True, copy=False)

    @api.constrains('name', 'date_pesee')
    def _check_unique_ticket(self):
        for t in self:
            if self.search_count([('name', '=', t.name), ('date_pesee', '=', t.date_pesee), ('id', '!=', t.id)]):
                raise UserError(_('Ce ticket de pesée existe déjà.'))

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._verifier()
        return recs

    def write(self, vals):
        if self.filtered(lambda t: t.state == 'valide') and set(vals) - {'purchase_id', 'state'}:
            raise UserError(_('Ticket validé : modification impossible (RG-1.6).'))
        return super().write(vals)

    def _verifier(self):
        for t in self.filtered(lambda t: t.state != 'valide'):
            ok = bool(t.partner_id and t.product_id and t.poids_net > 0 and t.lot_name)
            t.state = 'controle' if ok else 'a_controler'

    def _generer_commandes(self):
        Prix = self.env['ka.tarif']
        for t in self.filtered(lambda t: t.state == 'controle' and not t.purchase_id):
            lieu = t.lieu if not t.partner_id.ka_bareme_id else t.partner_id.ka_bareme_id.lieu
            prix = Prix.prix_pour(lieu, t.date_pesee)
            order = self.env['purchase.order'].create({
                'partner_id': t.partner_id.id, 'date_order': t.date_pesee, 'origin': t.name,
                'partner_ref': t.lot_name,
                'order_line': [(0, 0, {'product_id': t.product_id.id, 'name': t.product_id.display_name,
                                       'product_qty': t.poids_net, 'price_unit': prix,
                                       'date_planned': t.date_pesee})],
            })
            t.write({'purchase_id': order.id, 'state': 'valide'})
