from markupsafe import escape

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


def section_stockee(env, products):
    """Les articles de type stock sont imputés sur la section « achats stockés » (non modifiable), les autres
    sur les frais généraux d'exploitation."""
    code = 'ACHSTK' if any(p.is_storable for p in products) else 'FGEXP'
    return env['ka.section'].search([('code', '=', code)], limit=1)


class KaDa(models.Model):
    """Demande d'achat (§ 2.2.2 étape 1)."""
    _name = 'ka.da'
    _description = "Demande d'achat"
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° demande', readonly=True, copy=False, default='Nouveau')
    objet = fields.Char(string='Objet', default="Demande d'achat")
    site_id = fields.Many2one('ka.site', string='Site demandeur', required=True)
    demandeur = fields.Char(string='Demandeur', required=True)
    partner_id = fields.Many2one('res.partner', string='Fournisseur')
    date_besoin = fields.Date(string='Date du besoin', required=True)
    depot_id = fields.Many2one('stock.warehouse', string='Dépôt de réception')
    priorite = fields.Selection([('normale', 'Normale'), ('urgente', 'Urgente')], default='normale', string='Priorité')
    section_txt = fields.Char(compute='_compute_section', string='Section analytique')
    line_ids = fields.One2many('ka.da.ligne', 'da_id', string='Lignes')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    total = fields.Monetary(compute='_compute_section')
    state = fields.Selection([('en_cours', 'Brouillon'), ('a_signer', 'À signer'), ('signee', 'Signée'),
                              ('appel_offres', "En appel d'offres"), ('soldee', 'Commandée')],
                             default='en_cours', string='Statut', tracking=True)
    ao_ids = fields.One2many('ka.ao', 'da_id', string="Appels d'offres")

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — %s' % (self.name, self.objet or '')

    @api.depends('line_ids.montant', 'line_ids.product_id')
    def _compute_section(self):
        for d in self:
            d.total = sum(d.line_ids.mapped('montant'))
            sec = section_stockee(self.env, d.line_ids.product_id) if d.line_ids else self.env['ka.section']
            d.section_txt = '%s (auto)' % (sec.name or sec.code).split(' — ')[0] if sec else ''

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.da')
        return super().create(vals_list)

    def action_soumettre(self):
        for d in self:
            if not d.line_ids:
                raise UserError(_("La demande ne contient aucune ligne."))
            d.state = 'a_signer'

    def action_signer(self):
        self.filtered(lambda d: d.state == 'a_signer').write({'state': 'signee'})

    def action_demande_prix(self):
        """Appel d'offres : une offre vierge par fournisseur connu des articles (ou fournisseurs récents)."""
        self.ensure_one()
        if self.state not in ('en_cours', 'a_signer', 'signee'):
            raise UserError(_("Un appel d'offres est déjà lancé ou la demande est commandée."))
        if not self.line_ids:
            raise UserError(_("La demande ne contient aucune ligne."))
        partners = self.line_ids.product_id.seller_ids.partner_id[:3] or self.env['res.partner'].search(
            [('supplier_rank', '>', 0), ('ka_categorie', '=', 'frais_generaux')], limit=3)
        ao = self.env['ka.ao'].create({'da_id': self.id, 'offre_ids': [Command.create({
            'partner_id': p.id, 'ligne_ids': [Command.create({'da_ligne_id': l.id, 'prix': (
                l.product_id.seller_ids.filtered(lambda s: s.partner_id == p)[:1].price or 0.0)})
                for l in self.line_ids]}) for p in partners]})
        self.state = 'appel_offres'
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.ao', 'res_id': ao.id, 'view_mode': 'form'}

    def action_transformer(self):
        """Transforme la demande d'achat en commande d'achat (prix estimés)."""
        self.ensure_one()
        if self.state not in ('signee', 'appel_offres'):
            raise UserError(_("La demande doit être signée avant d'être transformée en commande."))
        cmd = self.env['ka.commande'].create({
            'site_id': self.site_id.id, 'partner_id': (self.partner_id or self.env.ref('kode_agri_achats.partner_divers')).id,
            'depot_id': self.depot_id.id, 'da_id': self.id,
            'line_ids': [Command.create({'product_id': l.product_id.id, 'designation': l.designation, 'qty': l.qty,
                                         'prix': (l.montant / l.qty) if l.qty else 0.0}) for l in self.line_ids]})
        self.state = 'soldee'
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.commande', 'res_id': cmd.id, 'view_mode': 'form'}


class KaDaLigne(models.Model):
    _name = 'ka.da.ligne'
    _description = "Ligne de demande d'achat"
    _order = 'sequence, id'

    da_id = fields.Many2one('ka.da', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Ligne', default=1000)
    product_id = fields.Many2one('product.product', string='Article', required=True)
    designation = fields.Char(string='Désignation')
    qty = fields.Float(string='Quantité', default=1.0, digits=(10, 0))
    uom_id = fields.Many2one('uom.uom', string='Unité')
    currency_id = fields.Many2one(related='da_id.currency_id')
    montant = fields.Monetary(string='Montant estimé')

    @api.onchange('product_id')
    def _onchange_product(self):
        if self.product_id:
            self.designation = self.product_id.name
            self.uom_id = self.product_id.uom_id
            self.montant = self.product_id.standard_price * (self.qty or 1)


class KaAo(models.Model):
    """Appel d'offres : tableau comparatif des réponses fournisseurs (§ 2.2.2 étape 2)."""
    _name = 'ka.ao'
    _description = "Appel d'offres"
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string="N° appel d'offres", readonly=True, copy=False, default='Nouveau')
    da_id = fields.Many2one('ka.da', string="Demande d'achat", required=True)
    offre_ids = fields.One2many('ka.ao.offre', 'ao_id', string='Réponses fournisseurs')
    commande_id = fields.Many2one('ka.commande', readonly=True, copy=False)
    state = fields.Selection([('ouverte', 'Ouvert'), ('comparee', 'Comparé'), ('retenue', 'Attribué'),
                              ('commandee', 'Commandé')], default='ouverte', string='Statut', tracking=True)
    comparatif_html = fields.Html(compute='_compute_comparatif', string='Comparatif des offres', sanitize=False)

    def _ka_subtitle(self):
        self.ensure_one()
        return "Tableau comparatif obtenu depuis la demande d'achat %s" % (self.da_id.name or '')

    @api.depends('name', 'da_id.name')
    def _compute_display_name(self):
        for ao in self:
            ao.display_name = '%s (issu de %s)' % (ao.name, ao.da_id.name) if ao.da_id else (ao.name or '')

    @api.depends('offre_ids.total', 'offre_ids.choix', 'offre_ids.delai', 'offre_ids.ligne_ids.prix', 'da_id.line_ids')
    def _compute_comparatif(self):
        """Tableau comparatif : une colonne de prix unitaire par article de la demande d'achat."""
        def fmt(x):
            return '{:,.0f}'.format(x or 0).replace(',', ' ')
        for ao in self:
            lignes = ao.da_id.line_ids
            tete = ''.join('<th class="o_ka_num">%s</th>' % escape(l.designation or l.product_id.name or '') for l in lignes)
            corps = ''
            for o in ao.offre_ids:
                prix = {ol.da_ligne_id.id: ol.prix for ol in o.ligne_ids}
                corps += '<tr><td>%s</td><td>%s j</td>%s<td class="o_ka_num">%s</td><td>%s</td></tr>' % (
                    escape(o.partner_id.name or ''), o.delai,
                    ''.join('<td class="o_ka_num">%s</td>' % fmt(prix.get(l.id)) for l in lignes),
                    fmt(o.total), '◉ Retenu' if o.choix else '○')
            ao.comparatif_html = ('<table class="o_ka_tbl"><thead><tr><th>Fournisseur</th><th>Délai</th>%s'
                                  '<th class="o_ka_num">Total HT</th><th>Choix</th></tr></thead><tbody>%s</tbody></table>'
                                  % (tete, corps))

    def action_comparer(self):
        """Compare les réponses reçues : le mieux-disant est mis en évidence dans le tableau comparatif."""
        for ao in self:
            if not ao.offre_ids.filtered(lambda o: o.total > 0):
                raise UserError(_("Saisissez les prix des fournisseurs avant de comparer les offres."))
            if ao.state == 'ouverte':
                ao.state = 'comparee'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.ao')
        return super().create(vals_list)

    def action_retenir(self):
        """Retient le mieux-disant (ou l'offre cochée) ; les autres réponses sont clôturées."""
        for ao in self:
            offres = ao.offre_ids.filtered(lambda o: o.total > 0)
            if not offres:
                raise UserError(_("Saisissez les prix des fournisseurs avant de retenir une offre."))
            choix = ao.offre_ids.filtered('choix')[:1] or offres.sorted('total')[:1]
            ao.offre_ids.write({'choix': False})
            choix.choix = True
            ao.state = 'retenue'

    def action_generer_commande(self):
        self.ensure_one()
        offre = self.offre_ids.filtered('choix')[:1]
        if not offre:
            raise UserError(_("Retenez d'abord un fournisseur."))
        da = self.da_id
        cmd = self.env['ka.commande'].create({
            'site_id': da.site_id.id, 'partner_id': offre.partner_id.id, 'depot_id': da.depot_id.id, 'da_id': da.id,
            'line_ids': [Command.create({'product_id': ol.da_ligne_id.product_id.id, 'designation': ol.da_ligne_id.designation,
                                         'qty': ol.da_ligne_id.qty, 'prix': ol.prix}) for ol in offre.ligne_ids]})
        self.write({'commande_id': cmd.id, 'state': 'commandee'})
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.commande', 'res_id': cmd.id, 'view_mode': 'form'}

    def action_relancer(self):
        return self.env['ka.structure']._notif(_('Relance'), _('Relance envoyée aux fournisseurs sans réponse.'))


class KaAoOffre(models.Model):
    _name = 'ka.ao.offre'
    _description = "Réponse d'un fournisseur à un appel d'offres"
    _order = 'total, id'

    ao_id = fields.Many2one('ka.ao', required=True, ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string='Fournisseur', required=True)
    delai = fields.Integer(string='Délai (j)')
    ligne_ids = fields.One2many('ka.ao.offre.ligne', 'offre_id', string='Prix par article')
    detail = fields.Char(compute='_compute_total', string='Prix unitaires')
    total = fields.Float(compute='_compute_total', string='Total HT', store=True, digits=(12, 0))
    choix = fields.Boolean(string='Retenu')
    choix_txt = fields.Char(compute='_compute_total', string='Choix')

    @api.depends('ligne_ids.prix', 'ligne_ids.da_ligne_id.qty', 'choix')
    def _compute_total(self):
        for o in self:
            o.total = sum(l.prix * l.da_ligne_id.qty for l in o.ligne_ids)
            o.choix_txt = 'Retenu' if o.choix else ''
            o.detail = ' / '.join('{:,.0f}'.format(l.prix).replace(',', ' ') for l in o.ligne_ids)


class KaAoOffreLigne(models.Model):
    _name = 'ka.ao.offre.ligne'
    _description = "Prix d'un article dans une offre"
    _order = 'id'

    offre_id = fields.Many2one('ka.ao.offre', required=True, ondelete='cascade')
    da_ligne_id = fields.Many2one('ka.da.ligne', string='Article', required=True)
    prix = fields.Float(string='Prix unitaire', digits=(12, 0))


class KaCommande(models.Model):
    """Commande d'achat : la signature génère la commande Odoo et sa réception (§ 2.2.2 étape 3)."""
    _name = 'ka.commande'
    _description = "Commande d'achat"
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° commande', readonly=True, copy=False, default='Nouveau')
    site_id = fields.Many2one('ka.site', string='Site de commande', required=True)
    partner_id = fields.Many2one('res.partner', string='Fournisseur', required=True)
    date_commande = fields.Date(string='Date commande', required=True, default=fields.Date.context_today)
    incoterm = fields.Char(string='Incoterm')
    depot_id = fields.Many2one('stock.warehouse', string='Dépôt')
    section_txt = fields.Char(compute='_compute_total', string='Section analytique')
    currency_id = fields.Many2one('res.currency', string='Devise', default=lambda s: s.env.company.currency_id)
    line_ids = fields.One2many('ka.commande.ligne', 'commande_id', string='Lignes')
    total = fields.Monetary(compute='_compute_total', string='Total HT', store=True)
    da_id = fields.Many2one('ka.da', string="Demande d'achat")
    po_id = fields.Many2one('purchase.order', string='Commande Odoo', readonly=True, copy=False)
    reception_ids = fields.One2many('ka.reception', 'commande_id', string='Réceptions')
    facture_ids = fields.One2many('ka.facture', 'commande_id', string='Factures')
    state = fields.Selection([('en_cours', 'Brouillon'), ('a_signer', 'À confirmer'), ('signee', 'Confirmée'),
                              ('recue', 'Reçue'), ('facturee', 'Facturée'), ('annulee', 'Annulée')],
                             default='en_cours', string='Statut', tracking=True)
    nb_receptions = fields.Integer(compute='_compute_nb_docs', string='Réception')
    nb_factures = fields.Integer(compute='_compute_nb_docs', string='Facture')
    type_lignes_txt = fields.Char(compute='_compute_nb_docs', string='Type ligne')

    def _ka_subtitle(self):
        self.ensure_one()
        return self.partner_id.name or ''

    @api.depends('reception_ids', 'facture_ids', 'line_ids.type')
    def _compute_nb_docs(self):
        labels = dict(self.env['ka.commande.ligne']._fields['type'].selection)
        for c in self:
            c.nb_receptions = len(c.reception_ids)
            c.nb_factures = len(c.facture_ids)
            types = []
            for t in c.line_ids.mapped('type'):
                if t and labels[t] not in types:
                    types.append(labels[t])
            c.type_lignes_txt = ' + '.join(types)

    def action_annuler(self):
        """Annule la commande tant qu'elle n'est ni reçue ni facturée (la commande Odoo liée est annulée)."""
        for c in self:
            if c.state in ('recue', 'facturee'):
                raise UserError(_('Une commande reçue ou facturée ne peut plus être annulée.'))
            if c.po_id and c.po_id.state not in ('cancel',):
                c.po_id.button_cancel()
            c.state = 'annulee'

    @api.depends('line_ids.montant', 'line_ids.product_id')
    def _compute_total(self):
        for c in self:
            c.total = sum(c.line_ids.mapped('montant'))
            sec = section_stockee(self.env, c.line_ids.product_id) if c.line_ids else self.env['ka.section']
            nom = (sec.name or sec.code or '').split(' — ')[0]
            c.section_txt = ('%s (auto, non modif.)' % nom) if sec and not sec.modifiable else ('%s (auto)' % nom if sec else '')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.commande')
        return super().create(vals_list)

    def action_soumettre(self):
        self.filtered(lambda c: c.state == 'en_cours').write({'state': 'a_signer'})

    def action_signer(self):
        """Signature : génère la commande Odoo confirmée, donc la réception adaptée (stockés en dépôt)."""
        for c in self:
            if c.state == 'annulee':
                raise UserError(_('La commande est annulée.'))
            if not c.line_ids:
                raise UserError(_('La commande ne contient aucune ligne.'))
            po = self.env['purchase.order'].create({
                'partner_id': c.partner_id.id, 'date_order': c.date_commande, 'origin': c.name,
                'picking_type_id': c.depot_id.in_type_id.id or False,
                'order_line': [Command.create({'product_id': l.product_id.id, 'name': l.designation or l.product_id.name,
                                               'product_qty': l.qty, 'price_unit': l.prix}) for l in c.line_ids]})
            po.button_confirm()
            c.write({'po_id': po.id, 'state': 'signee'})
            c.da_id.filtered(lambda d: d.state != 'soldee').write({'state': 'soldee'})

    def action_imprimer(self):
        return self.env['ka.structure']._notif(_('Commande'), _('Commande envoyée à l\'impression.'))

    def action_creer_reception(self):
        self.ensure_one()
        if self.state not in ('signee', 'recue'):
            raise UserError(_("Signez la commande avant de créer la réception."))
        picking = self.po_id.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))[:1]
        if not picking:
            raise UserError(_('Aucune réception en attente : la commande est entièrement reçue.'))
        rec = self.env['ka.reception'].create({'commande_id': self.id, 'picking_id': picking.id,
                                               'line_ids': [Command.create({
                                                   'sequence': 1000 * (i + 1), 'product_id': m.product_id.id,
                                                   'commande': m.product_uom_qty, 'recu': m.product_uom_qty})
                                                   for i, m in enumerate(picking.move_ids)]})
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.reception', 'res_id': rec.id, 'view_mode': 'form'}

    def action_open_receptions(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Réceptions', 'res_model': 'ka.reception',
                'view_mode': 'list,form', 'domain': [('commande_id', '=', self.id)]}

    def action_open_factures(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Factures', 'res_model': 'ka.facture',
                'view_mode': 'list,form', 'domain': [('commande_id', '=', self.id)]}


class KaCommandeLigne(models.Model):
    _name = 'ka.commande.ligne'
    _description = "Ligne de commande d'achat"
    _order = 'sequence, id'

    commande_id = fields.Many2one('ka.commande', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Ligne', default=1000)
    product_id = fields.Many2one('product.product', string='Article / service', required=True)
    designation = fields.Char(string='Désignation')
    type = fields.Selection([('stocke', 'Stockable'), ('service', 'Travaux'), ('conso', 'Consommable')],
                            compute='_compute_type', string='Type')
    qty = fields.Float(string='Quantité', default=1.0, digits=(10, 0))
    prix = fields.Float(string='Prix net', digits=(12, 0))
    currency_id = fields.Many2one(related='commande_id.currency_id')
    montant = fields.Monetary(compute='_compute_montant', string='Montant HT', store=True)

    @api.depends('product_id.type', 'product_id.is_storable')
    def _compute_type(self):
        for l in self:
            l.type = 'service' if l.product_id.type == 'service' else ('stocke' if l.product_id.is_storable else 'conso')

    @api.depends('qty', 'prix')
    def _compute_montant(self):
        for l in self:
            l.montant = l.qty * l.prix

    @api.onchange('product_id')
    def _onchange_product(self):
        if self.product_id:
            self.designation = self.product_id.name
            seller = self.product_id.seller_ids[:1]
            self.prix = seller.price or self.product_id.standard_price
