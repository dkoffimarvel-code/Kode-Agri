from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .equipement import nb

PREAVIS_RENOUVELLEMENT = 60   # jours avant l'échéance : le contrat passe « À renouveler »


class KaMntContrat(models.Model):
    """Contrat de maintenance avec un prestataire externe (§ 10.6) : périmètre, périodicité, coût forfaitaire ou à
    l'intervention, niveau de service ; les OT externalisés y sont rattachés."""
    _name = 'ka.mnt.contrat'
    _description = 'Contrat de maintenance'
    _inherit = ['ka.document', 'mail.thread', 'mail.activity.mixin']
    _order = 'date_fin, name'

    name = fields.Char(string='N° contrat', readonly=True, copy=False, default='Nouveau')
    prestataire_id = fields.Many2one('res.partner', string='Prestataire', required=True,
                                     help='Fournisseur du fichier des tiers (module Achats)')
    contact = fields.Char(string='Contact')
    telephone = fields.Char(string='Téléphone')
    perimetre = fields.Char(string='Périmètre', help='Ex. Séchoir tunnel n°1, n°2')
    equipement_ids = fields.Many2many('ka.mnt.equipement', string='Équipements couverts')
    type = fields.Selection([('intervention', "À l'intervention"), ('forfait', 'Forfaitaire')], string='Type de contrat',
                            required=True, default='intervention')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    tarif = fields.Monetary(string='Montant / tarif', required=True)
    unite_tarif = fields.Selection([('heure', 'h'), ('intervention', 'intervention'), ('mois', 'mois'), ('trimestre', 'trim.'),
                                    ('an', 'an')], string='Unité', default='heure', required=True)
    tarif_txt = fields.Char(compute='_compute_txt', string='Montant / tarif')
    tarif_label = fields.Char(compute='_compute_txt')
    date_debut = fields.Date(string='Date de début', required=True)
    date_fin = fields.Date(string='Date de fin', required=True)
    reconduction = fields.Selection([('oui', 'Oui'), ('non', 'Non')], string='Reconduction tacite', default='non')
    sla = fields.Char(string='Délai garanti (SLA)', help='Ex. < 24 h si criticité élevée')
    analytic_id = fields.Many2one('account.analytic.account', string='Axe analytique')
    periodicite_visite = fields.Integer(string='Visites préventives (mois)', help='0 = pas de visite contractuelle')
    prochaine_visite = fields.Date(string='Prochaine visite contractuelle')
    product_id = fields.Many2one('product.product', string='Prestation (article de service)',
                                 default=lambda s: s._default_product())
    ot_ids = fields.One2many('ka.mnt.ot', 'contrat_id', string='Historique des interventions')
    nb_ot = fields.Integer(compute='_compute_cumul', string='Ordres de travail')
    cout_cumule = fields.Monetary(compute='_compute_cumul', string='Cumul de l\'année')
    cout_txt = fields.Char(compute='_compute_cumul', string='Cumul')
    cout_label = fields.Char(compute='_compute_cumul')
    sous_titre = fields.Char(compute='_compute_txt')
    titre = fields.Char(compute='_compute_txt')
    state = fields.Selection([('brouillon', 'Brouillon'), ('actif', 'Actif'), ('a_renouveler', 'À renouveler'),
                              ('expire', 'Expiré'), ('cloture', 'Clôturé')], default='brouillon', string='Statut',
                             tracking=True)

    def _default_product(self):
        tmpl = self.env.ref('kode_agri_maintenance.product_prestation_mnt', raise_if_not_found=False)
        return tmpl.product_variant_id if tmpl else self.env['product.product']

    @api.depends('name', 'prestataire_id')
    def _compute_display_name(self):
        for c in self:
            c.display_name = '%s — %s' % (c.name, c.prestataire_id.name or '')

    def _ka_subtitle(self):
        self.ensure_one()
        return self.sous_titre

    @api.depends('tarif', 'unite_tarif', 'contact', 'telephone', 'name', 'prestataire_id', 'type')
    def _compute_txt(self):
        unites = dict(self._fields['unite_tarif'].selection)
        for c in self:
            c.tarif_txt = '%s F CFA / %s' % (nb(c.tarif), unites.get(c.unite_tarif, ''))
            c.tarif_label = _('Tarif horaire') if c.unite_tarif == 'heure' else _('Montant forfaitaire')
            c.titre = c.display_name
            c.sous_titre = ' · '.join(x for x in (_('Prestataire lié au fichier fournisseurs (module Achats)'),
                                                  _('Contact : %s') % c.contact if c.contact else '', c.telephone) if x)

    @api.depends('ot_ids.cout_total', 'ot_ids.state', 'ot_ids.date_cloture')
    def _compute_cumul(self):
        annee = fields.Date.context_today(self).year
        for c in self:
            c.nb_ot = len(c.ot_ids)
            c.cout_cumule = sum(c.ot_ids.filtered(lambda o: o.state == 'cloture' and o.date_cloture
                                                  and o.date_cloture.year == annee).mapped('cout_total'))
            c.cout_txt = nb(c.cout_cumule)
            c.cout_label = _('F CFA cumulés %s') % annee

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.mnt.contrat')
        return super().create(vals_list)

    def action_activer(self):
        for c in self:
            if c.date_fin < c.date_debut:
                raise UserError(_('La date de fin précède la date de début.'))
            c.state = 'actif'
            if c.periodicite_visite and not c.prochaine_visite:
                c.prochaine_visite = c.date_debut + timedelta(days=30 * c.periodicite_visite)
        self._verifier_echeances()

    def action_resilier(self):
        self.write({'state': 'cloture'})

    def action_renouveler(self):
        """Duplique le contrat pour la période suivante (même durée), en brouillon."""
        self.ensure_one()
        duree = self.date_fin - self.date_debut
        neuf = self.copy({'date_debut': self.date_fin + timedelta(days=1), 'date_fin': self.date_fin + timedelta(days=1) + duree,
                          'state': 'brouillon', 'prochaine_visite': False, 'equipement_ids': [Command.set(self.equipement_ids.ids)]})
        self.message_post(body=_('Renouvellement préparé : %s.') % neuf.name)
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.mnt.contrat', 'res_id': neuf.id, 'view_mode': 'form'}

    def action_generer_ot(self):
        """OT externalisé rattaché au contrat (correctif ou visite), sur le premier équipement du périmètre."""
        self.ensure_one()
        if self.state not in ('actif', 'a_renouveler'):
            raise UserError(_("Le contrat n'est pas en vigueur."))
        if not self.equipement_ids:
            raise UserError(_('Renseignez les équipements couverts par le contrat.'))
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.mnt.ot', 'view_mode': 'form',
                'context': {'default_contrat_id': self.id, 'default_externe': True,
                            'default_equipement_id': self.equipement_ids[:1].id, 'default_type': 'correctif'}}

    def action_planifier_visite(self):
        """Commande → OT : la visite contractuelle à échéance fait l'objet d'une commande confirmée auprès du prestataire,
        dont la confirmation génère l'OT préventif externalisé (pas de demande d'achat séparée)."""
        for c in self.filtered(lambda x: x.prochaine_visite and x.equipement_ids):
            site = c.equipement_ids[:1].site_id or self.env['ka.site'].search([], limit=1)
            montant = c.tarif if c.unite_tarif == 'intervention' else c.tarif * 4 if c.unite_tarif == 'heure' else 0.0
            cmd = self.env['ka.commande'].create({
                'site_id': site.id, 'partner_id': c.prestataire_id.id, 'date_commande': fields.Date.context_today(self),
                'line_ids': [Command.create({'product_id': c.product_id.id, 'designation': _('Visite contractuelle %s') % c.name,
                                             'qty': 1, 'prix': montant})]})
            cmd.action_signer()   # approbation donnée à la signature du contrat
            for e in c.equipement_ids:
                self.env['ka.mnt.ot'].create({
                    'equipement_id': e.id, 'type': 'preventif', 'priorite': 'normale', 'externe': True, 'contrat_id': c.id,
                    'commande_id': cmd.id, 'objet': _('Visite contractuelle du %s') % c.prochaine_visite.strftime('%d/%m/%Y'),
                    'date_demande': c.prochaine_visite})
            c.prochaine_visite = c.prochaine_visite + timedelta(days=30 * (c.periodicite_visite or 12))

    def action_open_ots(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Ordres de travail'), 'res_model': 'ka.mnt.ot',
                'view_mode': 'list,form', 'domain': [('contrat_id', '=', self.id)], 'context': {'default_contrat_id': self.id}}

    def _verifier_echeances(self):
        today = fields.Date.context_today(self)
        for c in self.filtered(lambda x: x.state in ('actif', 'a_renouveler')):
            if c.date_fin < today:
                c.state = 'expire'
            elif c.state == 'actif' and c.date_fin <= today + timedelta(days=PREAVIS_RENOUVELLEMENT):
                c.state = 'a_renouveler'
                c.activity_schedule('mail.mail_activity_data_todo', date_deadline=c.date_fin,
                                    summary=_("Renégocier l'échéance avant le %s (contrat à renouveler)") % c.date_fin.strftime('%d/%m/%Y'),
                                    user_id=self.env.user.id)

    @api.model
    def _cron_echeances(self):
        self.search([('state', 'in', ('actif', 'a_renouveler'))])._verifier_echeances()
        self.search([('state', '=', 'actif'), ('prochaine_visite', '<=', fields.Date.context_today(self))]).action_planifier_visite()
