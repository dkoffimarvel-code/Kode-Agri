from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

DOCS_REQUIS = ('Facture', 'BL', 'Commande')   # pièces obligatoires avant validation (RG-2.2, paramétrable)


class KaReception(models.Model):
    """Réception magasin avec gestion de la réception partielle (§ 2.3)."""
    _name = 'ka.reception'
    _description = 'Réception magasin'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° réception', readonly=True, copy=False, default='Nouveau')
    commande_id = fields.Many2one('ka.commande', string='Commande', required=True)
    picking_id = fields.Many2one('stock.picking', string='Réception Odoo', readonly=True)
    depot_txt = fields.Char(compute='_compute_depot', string='Dépôt')
    line_ids = fields.One2many('ka.reception.ligne', 'reception_id', string='Lignes')
    reliquat_total = fields.Float(compute='_compute_reliquat', digits=(10, 0))
    info = fields.Char(compute='_compute_reliquat')
    state = fields.Selection([('brouillon', 'À recevoir'), ('partielle', 'Partiellement reçu'), ('complete', 'Terminé')],
                             default='brouillon', string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        suivi = 'Réception partielle suivie' if self.reliquat_total else 'Réception complète'
        return 'Réception %s · %s' % ((self.depot_txt or '').lower(), suivi)

    @api.depends('name', 'commande_id.name')
    def _compute_display_name(self):
        for r in self:
            r.display_name = '%s (%s)' % (r.name, r.commande_id.name) if r.commande_id else (r.name or '')

    @api.depends('commande_id.depot_id')
    def _compute_depot(self):
        for r in self:
            r.depot_txt = 'magasin %s' % (r.commande_id.depot_id.name or '').lower().replace('magasin ', '')

    @api.depends('line_ids.reliquat', 'line_ids.product_id')
    def _compute_reliquat(self):
        for r in self:
            r.reliquat_total = sum(r.line_ids.mapped('reliquat'))
            restes = r.line_ids.filtered(lambda l: l.reliquat > 0)
            r.info = ('Réception partielle : %s %s à recevoir (réception complémentaire générée automatiquement).' % (
                ', '.join('%d %s' % (l.reliquat, (l.product_id.name or '').lower()) for l in restes),
                'restent' if r.reliquat_total > 1 else 'reste')) if restes else 'Réception complète : aucun reliquat.'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.reception')
        return super().create(vals_list)

    def action_valider(self):
        """Valide la réception : quantités reçues, reliquat conservé en reliquat de commande (backorder)."""
        for r in self:
            picking = r.picking_id
            if not picking or picking.state in ('done', 'cancel'):
                raise UserError(_("Cette réception est déjà validée ou annulée."))
            for l in r.line_ids:
                move = picking.move_ids.filtered(lambda m: m.product_id == l.product_id)[:1]
                if move:
                    move.quantity = l.recu
            picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
            r.state = 'partielle' if any(l.reliquat > 0 for l in r.line_ids) else 'complete'
            r.commande_id.state = 'recue' if r.state == 'complete' else r.commande_id.state

    def action_etiquettes(self):
        return self.env['ka.structure']._notif(_('Étiquettes'), _('Étiquettes de stockage imprimées.'))

    def action_reliquat(self):
        self.ensure_one()
        if not self.reliquat_total:
            raise UserError(_('Aucun reliquat à créer.'))
        return self.commande_id.action_creer_reception()


class KaReceptionLigne(models.Model):
    _name = 'ka.reception.ligne'
    _description = 'Ligne de réception'
    _order = 'sequence, id'

    reception_id = fields.Many2one('ka.reception', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Ligne', default=1000)
    product_id = fields.Many2one('product.product', string='Article', required=True)
    commande = fields.Float(string='Commandé', digits=(10, 0))
    recu = fields.Float(string='Reçu', digits=(10, 0))
    reliquat = fields.Float(compute='_compute_reliquat', string='Reliquat', digits=(10, 0), store=True)
    statut = fields.Char(string='Statut', default='A')
    emplacement = fields.Char(string='Emplacement')

    @api.depends('commande', 'recu')
    def _compute_reliquat(self):
        for l in self:
            l.reliquat = max(l.commande - l.recu, 0.0)


class KaFacture(models.Model):
    """Facture fournisseur et documents attachés ; pièces obligatoires exigées avant validation (RG-2.2)."""
    _name = 'ka.facture'
    _description = 'Facture fournisseur — documents attachés'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° facture', readonly=True, copy=False, default='Nouveau')
    commande_id = fields.Many2one('ka.commande', string='Commande', required=True)
    partner_id = fields.Many2one(related='commande_id.partner_id', string='Fournisseur', store=True)
    move_id = fields.Many2one('account.move', string='Facture comptable', readonly=True, copy=False)
    doc_ids = fields.One2many('ka.facture.doc', 'facture_id', string='Documents')
    nb_docs = fields.Integer(compute='_compute_docs', string='Documents attachés')
    requis_txt = fields.Char(compute='_compute_docs', string='Documents requis')
    state = fields.Selection([('brouillon', 'Brouillon'), ('provisoire', 'À contrôler'), ('validee', 'Comptabilisée')],
                             default='provisoire', string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — %s' % (self.name, self.partner_id.name or '')

    @api.depends('doc_ids.fourni', 'doc_ids.requis')
    def _compute_docs(self):
        for f in self:
            f.nb_docs = len(f.doc_ids.filtered('fourni'))
            req = f.doc_ids.filtered('requis')
            f.requis_txt = '%s / %s' % (len(req.filtered('fourni')), len(req))

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create([dict(v, name=self.env['ir.sequence'].next_by_code('ka.facture')) if v.get('name', 'Nouveau') == 'Nouveau' else v for v in vals_list])
        for f in recs.filtered(lambda f: not f.doc_ids):
            f.doc_ids = [Command.create({'name': '%s.pdf' % t, 'type': t, 'requis': True}) for t in DOCS_REQUIS]
        return recs

    def action_joindre(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Joindre un document', 'res_model': 'ir.attachment',
                'view_mode': 'form', 'target': 'new',
                'context': {'default_res_model': 'ka.facture', 'default_res_id': self.id}}

    def action_open_docs(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Pièces jointes', 'res_model': 'ka.facture.doc',
                'view_mode': 'list', 'domain': [('facture_id', '=', self.id)]}

    def action_telecharger(self):
        """Télécharge les fichiers joints à la facture (liste des pièces jointes enregistrées)."""
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Télécharger les pièces', 'res_model': 'ir.attachment',
                'view_mode': 'list,form', 'domain': [('res_model', '=', 'ka.facture'), ('res_id', '=', self.id)]}

    def action_controle(self):
        """Contrôle à trois voies : facture ↔ commande ↔ réceptions (quantités reçues)."""
        self.ensure_one()
        po = self.commande_id.po_id
        if not po:
            raise UserError(_("La commande n'est pas encore signée."))
        recu = sum(po.order_line.mapped('qty_received'))
        cmd = sum(po.order_line.mapped('product_qty'))
        return self.env['ka.structure']._notif(_('Contrôle facture'), _('Quantités reçues %s / commandées %s.') % (recu, cmd))

    def action_valider(self):
        """Validation de la facture : génère la facture fournisseur Odoo si toutes les pièces requises sont fournies."""
        for f in self:
            manque = f.doc_ids.filtered(lambda d: d.requis and not d.fourni)
            if manque:
                raise UserError(_('Pièces obligatoires manquantes : %s') % ', '.join(manque.mapped('type')))
            po = f.commande_id.po_id
            if po and not f.move_id:
                po.action_create_invoice()
                f.move_id = po.invoice_ids[:1]
            f.state = 'validee'
            f.commande_id.state = 'facturee'


class KaFactureDoc(models.Model):
    _name = 'ka.facture.doc'
    _description = 'Document attaché à une facture'
    _order = 'id'

    facture_id = fields.Many2one('ka.facture', required=True, ondelete='cascade')
    name = fields.Char(string='Document', required=True)
    type = fields.Char(string='Type')
    user_id = fields.Many2one('res.users', string='Ajouté par', default=lambda s: s.env.user)
    date = fields.Date(string='Date', default=fields.Date.context_today)
    requis = fields.Boolean(string='Pièce obligatoire')
    fourni = fields.Boolean(string='Fournie')
    statut = fields.Selection([('fournie', 'Fournie'), ('manquante', 'Manquante'), ('optionnelle', 'Optionnelle')],
                              compute='_compute_statut', string='Statut')

    @api.depends('requis', 'fourni')
    def _compute_statut(self):
        for d in self:
            d.statut = 'fournie' if d.fourni else ('manquante' if d.requis else 'optionnelle')


class KaTransfert(models.Model):
    """Transfert entre sites : sortie du site émetteur et entrée sur le site destinataire, lots tracés."""
    _name = 'ka.transfert'
    _description = 'Transfert intersites'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° transfert', readonly=True, copy=False, default='Nouveau')
    emetteur_id = fields.Many2one('stock.warehouse', string='Site émetteur', required=True)
    destinataire_id = fields.Many2one('stock.warehouse', string='Site destinataire', required=True)
    date_prevue = fields.Date(string='Date prévue')
    responsable = fields.Char(string='Responsable', default='Magasinier')
    line_ids = fields.One2many('ka.transfert.ligne', 'transfert_id', string='Lignes')
    state = fields.Selection([('brouillon', 'Brouillon'), ('a_valider', 'Prêt'), ('valide', 'Transféré')],
                             default='a_valider', string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s → %s' % (self.emetteur_id.name or '', self.destinataire_id.name or '')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.transfert')
        return super().create(vals_list)

    def action_valider(self):
        for t in self:
            if t.emetteur_id == t.destinataire_id:
                raise UserError(_("Les sites émetteur et destinataire doivent être différents."))
            for l in t.line_ids:
                self.env['stock.lot'].ka_move(l.product_id, l.lot_id, l.qty, t.emetteur_id.lot_stock_id,
                                              t.destinataire_id.lot_stock_id)
            t.state = 'valide'

    def action_imprimer(self):
        return self.env['ka.structure']._notif(_('Bon de transfert'), _('Bon imprimé.'))


class KaTransfertLigne(models.Model):
    _name = 'ka.transfert.ligne'
    _description = 'Ligne de transfert'

    transfert_id = fields.Many2one('ka.transfert', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Article', required=True)
    qty = fields.Float(string='Quantité', digits=(10, 0))
    uom_id = fields.Many2one(related='product_id.uom_id', string='Unité')
    lot_id = fields.Many2one('stock.lot', string='Lot', domain="[('product_id', '=', product_id)]")
    statut = fields.Char(string='Statut', default='A')


class KaInventaire(models.Model):
    """Commande d'inventaire : comptage et ajustement valorisé (§ 2.3)."""
    _name = 'ka.inventaire'
    _description = "Commande d'inventaire"
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string="N° inventaire", readonly=True, copy=False, default='Nouveau')
    libelle = fields.Char(string='Libellé', default='Inventaire tournant')
    depot_id = fields.Many2one('stock.warehouse', string='Dépôt', required=True)
    line_ids = fields.One2many('ka.inventaire.ligne', 'inventaire_id', string='Comptages')
    state = fields.Selection([('session', 'Brouillon'), ('comptage', 'En comptage'), ('validee', 'Validé')],
                             default='session', string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — %s' % (self.libelle or '', self.depot_id.name or '')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.inventaire')
        return super().create(vals_list)

    def action_demarrer(self):
        self.filtered(lambda i: i.state == 'session').write({'state': 'comptage'})

    def action_valider(self):
        """Applique les écarts comme ajustements d'inventaire valorisés (distribution analytique incluse)."""
        Quant = self.env['stock.quant'].with_context(inventory_mode=True)
        for i in self:
            if i.state == 'validee':
                continue
            quants = self.env['stock.quant']
            for l in i.line_ids.filtered(lambda l: l.ecart):
                quants |= Quant.create({'product_id': l.product_id.id, 'location_id': l.location_id.id,
                                        'inventory_quantity': l.compte})
            if quants:
                quants.action_apply_inventory()
            i.state = 'validee'

    def action_imprimer(self):
        return self.env['ka.structure']._notif(_('Fiches de comptage'), _('Fiches imprimées.'))


class KaInventaireLigne(models.Model):
    _name = 'ka.inventaire.ligne'
    _description = "Ligne d'inventaire"

    inventaire_id = fields.Many2one('ka.inventaire', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Article', required=True)
    location_id = fields.Many2one('stock.location', string='Emplacement', required=True,
                                  domain=[('usage', '=', 'internal')])
    theorique = fields.Float(string='Théorique', digits=(10, 0))
    compte = fields.Float(string='Compté', digits=(10, 0))
    ecart = fields.Float(compute='_compute_ecart', string='Écart', digits=(10, 0), store=True)

    @api.depends('theorique', 'compte')
    def _compute_ecart(self):
        for l in self:
            l.ecart = l.compte - l.theorique

    @api.onchange('product_id', 'location_id')
    def _onchange_theorique(self):
        if self.product_id and self.location_id:
            quants = self.env['stock.quant'].search([('product_id', '=', self.product_id.id),
                                                     ('location_id', '=', self.location_id.id)])
            self.theorique = sum(quants.mapped('quantity'))
            self.compte = self.theorique
