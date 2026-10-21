from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .common import anciennete, fcfa


class KaRhEmploye(models.Model):
    """Dossier administratif du salarié : identité, contrat, poste, affectation, rémunération et compétences (§ 7.1).
    Le dossier crée le contact « salarié » utilisé par les notes de frais (module 6) et les écritures de paie."""
    _name = 'ka.rh.employe'
    _description = 'Dossier du personnel'
    _inherit = ['ka.document', 'mail.thread', 'mail.activity.mixin']
    _order = 'matricule'

    matricule = fields.Char(string='Matricule', readonly=True, copy=False, default='Nouveau')
    name = fields.Char(string='Nom et prénoms', required=True, tracking=True)
    poste = fields.Char(string='Poste', required=True, tracking=True)
    categorie_id = fields.Many2one('ka.rh.categorie', string='Catégorie professionnelle')
    affectation_id = fields.Many2one('ka.rh.affectation', string='Affectation', required=True, tracking=True)
    affectation_libelle = fields.Char(related='affectation_id.libelle')
    analytic_id = fields.Many2one('account.analytic.account', string='Compte analytique')
    responsable = fields.Char(related='affectation_id.responsable', string='Responsable hiérarchique')
    type_contrat = fields.Selection([('cdi', 'CDI'), ('cdd', 'CDD'), ('stage', 'Stage'), ('journalier', 'Journalier')],
                                    string='Type contrat', default='cdi', required=True)
    date_entree = fields.Date(string='Date entrée', required=True, default=fields.Date.context_today)
    date_fin_contrat = fields.Date(string='Fin de contrat (CDD)')
    date_sortie = fields.Date(string='Date de sortie', readonly=True, copy=False)
    essai_mois = fields.Integer(string="Période d'essai (mois)")
    date_fin_essai = fields.Date(compute='_compute_essai', string="Fin de période d'essai", store=True)
    visite_medicale = fields.Date(string="Certificat d'aptitude (visite médicale)")
    contrat_ref = fields.Char(string='Contrat', readonly=True, copy=False)
    situation = fields.Selection([('celibataire', 'Célibataire'), ('marie', 'Marié(e)'), ('divorce', 'Divorcé(e)'),
                                  ('veuf', 'Veuf / veuve')], string='Situation familiale', default='celibataire')
    nb_enfants = fields.Integer(string='Enfants à charge')
    parts = fields.Float(compute='_compute_parts', string='Parts (RICF)', digits=(4, 1))
    horaire_hebdo = fields.Float(string='Horaire théorique hebdomadaire', default=40.0, digits=(5, 2))
    badge = fields.Char(string='Badge / identifiant de pointage', copy=False,
                        help='Numéro de badge, code RFID ou identifiant biométrique transmis par la pointeuse')
    pin = fields.Char(string='Code PIN', copy=False)
    telephone = fields.Char(string='Téléphone')
    banque = fields.Char(string='Compte bancaire / mobile money')
    element_ids = fields.One2many('ka.rh.element', 'employe_id', string='Éléments de rémunération')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    salaire_base = fields.Monetary(compute='_compute_salaire', string='Salaire de base', store=True)
    taux_horaire = fields.Monetary(compute='_compute_salaire', string='Taux horaire')
    competence_ids = fields.One2many('ka.rh.competence.niveau', 'employe_id', string='Compétences')
    solde_ids = fields.One2many('ka.rh.solde', 'employe_id', string='Soldes de congés')
    partner_id = fields.Many2one('res.partner', string='Contact salarié', readonly=True, copy=False)
    anciennete_mois = fields.Integer(compute='_compute_anciennete', string='Ancienneté (mois)')
    anciennete_txt = fields.Char(compute='_compute_anciennete', string='Ancienneté')
    nb_bulletins = fields.Integer(compute='_compute_nb')
    nb_demandes = fields.Integer(compute='_compute_nb')
    state = fields.Selection([('brouillon', 'Brouillon'), ('actif', 'Actif'), ('sorti', 'Sorti')], default='brouillon',
                             string='Statut', tracking=True)

    @api.depends('matricule', 'poste')
    def _compute_display_name(self):
        for e in self:
            e.display_name = '%s — %s' % (e.matricule, e.poste or e.name or '')

    def _ka_subtitle(self):
        self.ensure_one()
        return ' · '.join(x for x in (self.matricule, self.name, self.affectation_libelle or self.affectation_id.name) if x)

    @api.depends('date_entree', 'essai_mois')
    def _compute_essai(self):
        for e in self:
            e.date_fin_essai = (e.date_entree + relativedelta(months=e.essai_mois)) if e.date_entree and e.essai_mois else False

    @api.depends('situation', 'nb_enfants')
    def _compute_parts(self):
        for e in self:
            base = 2.0 if e.situation == 'marie' else (1.5 if e.situation in ('divorce', 'veuf') and e.nb_enfants else 1.0)
            e.parts = min(base + 0.5 * (e.nb_enfants or 0), 5.0)

    @api.depends('element_ids.montant', 'element_ids.rubrique_id', 'horaire_hebdo')
    def _compute_salaire(self):
        for e in self:
            e.salaire_base = sum(e.element_ids.filtered(lambda l: l.rubrique_id.categorie == 'base').mapped('montant'))
            mensuel = (e.horaire_hebdo or 40.0) * 52 / 12
            e.taux_horaire = e.salaire_base / mensuel if mensuel else 0.0

    def _compute_anciennete(self):
        today = fields.Date.context_today(self)
        for e in self:
            e.anciennete_mois, e.anciennete_txt = anciennete(e.date_entree, e.date_sortie or today)

    def _compute_nb(self):
        for e in self:
            e.nb_bulletins = self.env['ka.rh.bulletin'].search_count([('employe_id', '=', e.id)]) if e.id else 0
            e.nb_demandes = self.env['ka.rh.demande'].search_count([('employe_id', '=', e.id)]) if e.id else 0

    @api.constrains('essai_mois', 'categorie_id')
    def _check_essai(self):
        for e in self:   # RG-7.7 : pas au-delà du maximum de la catégorie professionnelle
            if e.categorie_id and e.essai_mois > e.categorie_id.essai_mois:
                raise ValidationError(_("La période d'essai (%s mois) dépasse le maximum de la catégorie %s (%s mois) "
                                        "(RG-7.7).") % (e.essai_mois, e.categorie_id.name, e.categorie_id.essai_mois))

    @api.constrains('badge')
    def _check_badge(self):
        for e in self.filtered('badge'):
            if self.search_count([('badge', '=', e.badge)]) > 1:
                raise ValidationError(_('Le badge %s est déjà attribué.') % e.badge)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('matricule', 'Nouveau') == 'Nouveau':
                vals['matricule'] = self.env['ir.sequence'].next_by_code('ka.rh.employe')
            if not vals.get('essai_mois') and vals.get('categorie_id'):
                vals['essai_mois'] = self.env['ka.rh.categorie'].browse(vals['categorie_id']).essai_mois
        recs = super().create(vals_list)
        recs._sync_partner()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if {'name', 'matricule', 'telephone'} & set(vals):
            self._sync_partner()
        return res

    def _sync_partner(self):
        """Contact « salarié » (module 6) : tiers des notes de frais, de la paie et des avances de mission."""
        for e in self:
            vals = {'name': e.name, 'ka_salarie': True, 'ka_matricule': e.matricule, 'phone': e.telephone}
            if e.partner_id:
                e.partner_id.write(vals)
            else:
                e.partner_id = self.env['res.partner'].create(vals)

    # ---- actions ------------------------------------------------------------------------------------------------
    def action_activer(self):
        for e in self:
            if not e.element_ids.filtered(lambda l: l.rubrique_id.categorie == 'base'):
                raise UserError(_('Renseignez le salaire de base avant d\'activer le dossier.'))
            e.state = 'actif'
            e._init_soldes()

    def _init_soldes(self):
        for t in self.env['ka.rh.type.conge'].search([('deductible', '=', True)]):
            if not self.solde_ids.filtered(lambda s: s.type_id == t):
                self.env['ka.rh.solde'].create({'employe_id': self.id, 'type_id': t.id})

    def action_generer_contrat(self):
        """Génère la référence du contrat (CDI ou CDD) mentionnant la période d'essai (§ 7.5.4)."""
        for e in self:
            if not e.contrat_ref:
                e.contrat_ref = self.env['ir.sequence'].next_by_code('ka.rh.contrat')
            essai = (_(", période d'essai jusqu'au %s") % e.date_fin_essai.strftime('%d/%m/%Y')) if e.date_fin_essai else ''
            e.message_post(body=_('Contrat %s (%s) généré%s.') % (e.contrat_ref, dict(self._fields['type_contrat'].selection)[e.type_contrat], essai))
        return self.env['ka.rh.employe']._notif(_('Contrat'), _('Contrat %s généré.') % ', '.join(self.mapped('contrat_ref')))

    def action_sortir(self):
        """Sortie du collaborateur : indemnité compensatrice des congés acquis non pris (RG-7.2)."""
        for e in self:
            e.write({'state': 'sorti', 'date_sortie': fields.Date.context_today(self)})
            reste = sum(e.solde_ids.filtered(lambda s: s.type_id.code == 'CA').mapped('solde'))
            if reste > 0:
                indemnite = reste * e.salaire_base / 26.0
                e.message_post(body=_('Indemnité compensatrice de congés payés : %s jours, soit %s FCFA, à verser en paie.')
                               % (round(reste, 1), fcfa(indemnite)))

    def action_open_bulletins(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Bulletins', 'res_model': 'ka.rh.bulletin',
                'view_mode': 'list,form', 'domain': [('employe_id', '=', self.id)]}

    def action_open_demandes(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Demandes', 'res_model': 'ka.rh.demande',
                'view_mode': 'list,form', 'domain': [('employe_id', '=', self.id)]}

    @api.model
    def _notif(self, titre, message, typ='info'):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': titre, 'message': message, 'type': typ, 'sticky': False}}


class KaRhElement(models.Model):
    """Élément de rémunération du contrat : salaire de base, primes et indemnités fixes ou variables."""
    _name = 'ka.rh.element'
    _description = 'Élément de rémunération'
    _order = 'sequence, id'

    employe_id = fields.Many2one('ka.rh.employe', required=True, ondelete='cascade')
    rubrique_id = fields.Many2one('ka.rh.rubrique', string='Rubrique', required=True, domain=[('nature', '=', 'gain')])
    sequence = fields.Integer(related='rubrique_id.sequence', store=True)
    type = fields.Selection([('fixe_mensuel', 'Fixe mensuel'), ('variable', 'Variable'), ('fixe', 'Fixe')],
                            string='Type', default='fixe', required=True)
    currency_id = fields.Many2one(related='employe_id.currency_id')
    montant = fields.Monetary(string='Montant', required=True)
