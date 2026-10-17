from odoo import _, api, fields, models
from odoo.exceptions import UserError


class KaGeneration(models.Model):
    _name = 'ka.generation'
    _description = 'Génération des réceptions et factures'
    _inherit = ['ka.document']
    _order = 'name desc'

    name = fields.Char(string='Tâche', readonly=True, copy=False, default='Nouveau')
    date_debut = fields.Date(string='Date début pesée', required=True)
    date_fin = fields.Date(string='Date fin pesée', required=True)
    date_comptable = fields.Date(string='Date comptable', required=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Site')
    categorie = fields.Selection([('planteur_coop', 'Planteur & coopérative')], string='Catégorie fournisseur',
                                 default='planteur_coop')
    groupage = fields.Selection([('fournisseur', 'Réception + facture par fournisseur')], string='Groupage',
                                default='fournisseur')
    avances = fields.Boolean(string='Avances à imputer', default=True)
    primes = fields.Boolean(string='Primes à ventiler', default=True)
    state = fields.Selection([('pret', 'Prêt à lancer'), ('simule', 'Simulé'), ('termine', 'Terminé')],
                             default='pret', string='Statut')
    nb_commandes = fields.Integer(compute='_compute_controles', string='Commandes éligibles sur la plage')
    nb_hors_periode = fields.Integer(compute='_compute_controles', string='Tickets hors période comptable')
    trace = fields.Text(string='Trace', readonly=True)

    def _ka_subtitle(self):
        return 'Tâche %s — groupage par plage de dates de pesée' % (self.name or '')

    def _tickets(self):
        self.ensure_one()
        return self.env['ka.ticket'].search([
            ('state', '=', 'valide'), ('date_pesee', '>=', self.date_debut), ('date_pesee', '<=', self.date_fin),
            ('purchase_id.state', 'in', ('draft', 'sent', 'to approve', 'purchase')),
            ('purchase_id.invoice_ids', '=', False)])

    @api.depends('date_debut', 'date_fin', 'date_comptable')
    def _compute_controles(self):
        for rec in self:
            tickets = rec._tickets() if rec.date_debut and rec.date_fin else self.env['ka.ticket']
            rec.nb_commandes = len(tickets)
            rec.nb_hors_periode = len(tickets.filtered(
                lambda t: rec.date_comptable and
                (t.date_pesee.year, t.date_pesee.month) > (rec.date_comptable.year, rec.date_comptable.month)
            )) if tickets else 0
            # RG-1.7 : on ne facture pas un mois antérieur sur un mois ultérieur.
            rec.nb_hors_periode += len(tickets.filtered(
                lambda t: rec.date_comptable and
                (t.date_pesee.year, t.date_pesee.month) < (rec.date_comptable.year, rec.date_comptable.month)))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.generation')
        return super().create(vals_list)

    def action_simuler(self):
        self.ensure_one()
        self.trace = _('Simulation : %s commande(s) éligible(s), %s ticket(s) hors période.') % (
            self.nb_commandes, self.nb_hors_periode)
        self.state = 'simule'

    def action_planifier(self):
        self.ensure_one()
        cron = self.env.ref('kode_agri_planteur.cron_generation_batch', raise_if_not_found=False)
        if cron:
            cron.sudo().write({'active': True, 'nextcall': fields.Datetime.now()})
        return True

    def action_lancer(self):
        self.ensure_one()
        if self.nb_hors_periode:
            raise UserError(_("RG-1.7 : des tickets d'un mois différent de la date comptable ne peuvent pas "
                              "être facturés ensemble."))
        orders = self._tickets().mapped('purchase_id')
        for order in orders.filtered(lambda o: o.state in ('draft', 'sent')):
            order.button_confirm()
        for picking in orders.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
            picking.action_confirm()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                # le numéro de lot du pont-bascule est repris tel quel (article suivi par lot)
                ticket = self.env['ka.ticket'].search([('purchase_id', '=', move.purchase_line_id.order_id.id)], limit=1)
                if ticket.lot_name and move.product_id.tracking == 'lot':
                    move.move_line_ids.write({'lot_name': ticket.lot_name})
            picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
        invoices = self.env['account.move']
        for partner in orders.partner_id:
            pos = orders.filtered(lambda o: o.partner_id == partner)
            pos.action_create_invoice()
            invoices |= pos.invoice_ids
        invoices.filtered(lambda m: m.state == 'draft').write({'invoice_date': self.date_comptable,
                                                              'date': self.date_comptable})
        self.write({'state': 'termine', 'trace': _('%s commande(s), %s facture(s) fournisseur générée(s).') % (
            len(orders), len(invoices))})

    def action_trace(self):
        return {'type': 'ir.actions.act_window', 'name': 'Trace', 'res_model': 'ka.generation',
                'res_id': self.id, 'view_mode': 'form', 'target': 'new'}

    @api.model
    def cron_run(self):
        for gen in self.search([('state', '=', 'pret')]):
            gen.action_lancer()
