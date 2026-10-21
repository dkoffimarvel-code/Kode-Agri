from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class KaLivraison(models.Model):
    """Bon d'expédition : sortie usine et transfert vers le parc terre-plein (§ 5.4.2)."""
    _name = 'ka.livraison'
    _description = "Bon d'expédition — livraison"
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° bon', readonly=True, copy=False, default='Nouveau')
    conteneur_id = fields.Many2one('ka.conteneur', string='Conteneur', required=True)
    sous_contrat_id = fields.Many2one(related='conteneur_id.sous_contrat_id', string='Sous-contrat', store=True)
    voyage_id = fields.Many2one('ka.voyage', string='Ordre de voyage')
    plomb = fields.Char(related='conteneur_id.plomb', string='N° de plomb')
    date_sortie = fields.Date(string='Date de sortie usine', required=True, default=fields.Date.context_today)
    transporteur_id = fields.Many2one('res.partner', string='Transporteur')
    immatriculation = fields.Char(string='Immatriculation')
    chauffeur = fields.Char(string='Chauffeur')
    destination_id = fields.Many2one('stock.location', string='Site de destination',
                                     default=lambda s: s.env.ref('kode_agri_vente.loc_terre_plein', raise_if_not_found=False))
    date_arrivee_parc = fields.Date(string="Date d'arrivée au parc terre-plein")
    state = fields.Selection([('pret', 'Prêt'), ('brouillon', 'À valider'), ('empote', 'Sorti usine'),
                              ('parc', 'Au parc terre-plein')], default='brouillon', string='Statut', tracking=True)
    statut_conteneur = fields.Selection(related='conteneur_id.state', string='Statut conteneur')
    statut_conteneur_txt = fields.Char(compute='_compute_statut_conteneur_txt', string='Statut conteneur (pastille)')

    @api.depends('conteneur_id.state')
    def _compute_statut_conteneur_txt(self):
        for l in self:
            lib = dict(self.env['ka.conteneur']._fields['state'].selection).get(l.conteneur_id.state, '')
            l.statut_conteneur_txt = ('Statut conteneur : %s' % lib) if lib else ''

    @api.depends('name', 'sous_contrat_id')
    @api.depends_context('ka_nom_long_bl')
    def _compute_display_name(self):
        """Fil d'Ariane de l'écran 5.4b : « BL-0188 (SC-0061-03) »."""
        long = self.env.context.get('ka_nom_long_bl')
        for l in self:
            l.display_name = ('%s (%s)' % (l.name, l.sous_contrat_id.name)) if long and l.sous_contrat_id else (l.name or '')

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — sous-contrat %s · conteneur %s' % (self.name, self.sous_contrat_id.name or '', self.conteneur_id.name or '')

    @api.onchange('conteneur_id')
    def _onchange_conteneur(self):
        v = self.conteneur_id.voyage_id
        if v:
            self.voyage_id, self.transporteur_id, self.immatriculation = v, v.transporteur_id, v.vehicule
            self.chauffeur = v.conducteur

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.livraison')
        return super().create(vals_list)

    def action_valider(self):
        """Sort les colis du stock usine vers le parc terre-plein ; le conteneur et son n° de série passent « Empoté »."""
        for l in self:
            if l.state not in ('pret', 'brouillon'):
                continue
            if l.conteneur_id.state not in ('empote', 'plombe'):
                raise UserError(_("Le conteneur doit être empoté avant validation du bon d'expédition."))
            l.conteneur_id._transferer_colis(l.destination_id)
            l.conteneur_id.write({'state': 'empote'})
            l.state = 'empote'

    def write(self, vals):
        res = super().write(vals)
        if vals.get('date_arrivee_parc'):
            for l in self:
                l.conteneur_id.date_entree_parc = l.date_arrivee_parc
            self.filtered(lambda l: l.state == 'empote').write({'state': 'parc'})
        return res

    def action_enregistrer_enlevement(self):
        """Écran 5.4b : enregistre l'enlèvement du conteneur (camion, transporteur, chauffeur) avant validation du BL."""
        for l in self:
            if not (l.transporteur_id and l.immatriculation):
                raise UserError(_("Renseignez le fournisseur transporteur et l'immatriculation du camion."))
            if l.state == 'pret':
                l.state = 'brouillon'

    def action_bordereau(self):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Bordereau'), 'type': 'success', 'sticky': False,
                           'message': _("Bordereau d'expédition du conteneur imprimé.")}}

    def action_planning(self):
        return {'type': 'ir.actions.act_window', 'name': 'Planning camions', 'res_model': 'ka.voyage',
                'view_mode': 'list,form'}
