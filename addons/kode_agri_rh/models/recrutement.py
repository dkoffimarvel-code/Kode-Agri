from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .common import fcfa

SEUIL_DIRECTION = 500000   # masse salariale mensuelle au-delà de laquelle la direction valide (paramètre)
ETAPES = [('nouvelle', 'Nouvelle'), ('preselection', 'Présélection'), ('entretien', 'Entretien'), ('test', 'Test'),
          ('proposition', 'Proposition'), ('recrutee', 'Recrutée'), ('refusee', 'Refusée')]


class KaRhDemandePersonnel(models.Model):
    """Demande de personnel : préalable à toute ouverture de poste, validée par la hiérarchie, les RH et, selon le seuil
    budgétaire ou pour une création de poste, par la direction (§ 7.5.1, RG-7.6)."""
    _name = 'ka.rh.demande.personnel'
    _description = 'Demande de personnel'
    _inherit = ['ka.document', 'mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(string='N° demande', readonly=True, copy=False, default='Nouveau')
    poste = fields.Char(string='Poste concerné', required=True)
    affectation_id = fields.Many2one('ka.rh.affectation', string='Atelier ou service', required=True)
    demandeur = fields.Char(string='Demandeur', required=True)
    motif = fields.Selection([('depart', 'Remplacement (départ)'), ('mobilite', 'Remplacement (mobilité interne)'),
                              ('creation', 'Création de poste')], string='Motif', required=True, default='depart')
    type_contrat = fields.Selection([('cdi', 'CDI'), ('cdd', 'CDD')], string='Type de contrat souhaité', default='cdi')
    effectif = fields.Integer(string='Effectif demandé', default=1)
    date_souhaitee = fields.Date(string='Date de prise de fonction souhaitée')
    categorie_id = fields.Many2one('ka.rh.categorie', string='Catégorie professionnelle')
    categorie_txt = fields.Char(string='Catégorie (libellé)', help='Ex. Ouvrier — atelier production')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    budget = fields.Monetary(string='Budget / masse salariale (mensuel)')
    budget_txt = fields.Char(compute='_compute_txt', string='Budget / masse salariale')
    ligne_budgetaire = fields.Char(string='Ligne budgétaire')
    justification = fields.Text(string='Justification')
    valide_hierarchie = fields.Boolean(string='Validée par la hiérarchie', readonly=True, copy=False)
    valide_rh = fields.Boolean(string='Validée par les RH', readonly=True, copy=False)
    valide_direction = fields.Boolean(string='Validée par la direction', readonly=True, copy=False)
    direction_requise = fields.Boolean(compute='_compute_txt', string='Validation direction requise')
    circuit_txt = fields.Char(compute='_compute_txt', string='Étape de validation')
    candidature_ids = fields.One2many('ka.rh.candidature', 'demande_id', string='Candidatures')
    nb_candidatures = fields.Integer(compute='_compute_txt')
    titre = fields.Char(compute='_compute_txt')
    state = fields.Selection([('brouillon', 'Brouillon'), ('a_valider', 'À valider'), ('approuvee', 'Approuvée'),
                              ('poste_ouvert', 'Poste ouvert'), ('pourvu', 'Pourvu'), ('refusee', 'Refusée')],
                             default='brouillon', string='Statut', tracking=True)

    @api.depends('name', 'state')
    def _compute_display_name(self):
        for d in self:
            d.display_name = '%s — %s' % (d.name, _('Nouvelle demande') if d.state in ('brouillon', 'a_valider') else d.poste)

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s · %s' % (self.affectation_id.name or '', _('Demandeur : %s') % (self.demandeur or ''))

    @api.depends('budget', 'motif', 'valide_hierarchie', 'valide_rh', 'valide_direction', 'candidature_ids')
    def _compute_txt(self):
        seuil = float(self.env['ir.config_parameter'].sudo().get_param('kode_agri_rh.seuil_direction', SEUIL_DIRECTION))
        for d in self:
            d.budget_txt = '%s FCFA / mois' % fcfa(d.budget)
            d.titre = _('Demande de personnel — %s') % (d.poste or '')
            d.direction_requise = d.motif == 'creation' or d.budget * (d.effectif or 1) > seuil   # RG-7.6
            etapes = [(_('Responsable hiérarchique'), d.valide_hierarchie), (_('Responsable RH'), d.valide_rh)]
            if d.direction_requise:
                etapes.append((_('Direction'), d.valide_direction))
            suivant = [n for n, ok in etapes if not ok]
            d.circuit_txt = (_('En attente : %s') % suivant[0]) if suivant else _('Circuit complet')
            d.nb_candidatures = len(d.candidature_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.rh.demande.personnel')
        return super().create(vals_list)

    def action_soumettre(self):
        for d in self.filtered(lambda x: x.state == 'brouillon'):
            d.state = 'a_valider'
            d.activity_schedule('mail.mail_activity_data_todo', summary=_('Demande de personnel %s à valider') % d.name,
                                user_id=self.env.user.id)

    def action_valider(self):
        """Une étape du circuit par clic : hiérarchie → RH → direction (création de poste ou au-delà du seuil)."""
        for d in self.filtered(lambda x: x.state == 'a_valider'):
            if not d.valide_hierarchie:
                d.valide_hierarchie = True
            elif not d.valide_rh:
                d.valide_rh = True
            elif d.direction_requise and not d.valide_direction:
                d.valide_direction = True
            if d.valide_hierarchie and d.valide_rh and (d.valide_direction or not d.direction_requise):
                d.state = 'approuvee'
                d.activity_ids.action_feedback(feedback=_('Approuvée'))
            else:
                d.message_post(body=d.circuit_txt)

    def action_refuser(self):
        self.filtered(lambda x: x.state == 'a_valider').write({'state': 'refusee'})

    def action_ouvrir_poste(self):
        """Ouverture du poste et publication de l'offre : uniquement sur demande approuvée (RG-7.6)."""
        for d in self:
            if d.state != 'approuvee':
                raise UserError(_("Aucune offre n'est diffusée sans demande de personnel approuvée (RG-7.6)."))
            d.state = 'poste_ouvert'

    def action_open_candidatures(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Candidatures'), 'res_model': 'ka.rh.candidature',
                'view_mode': 'list,form', 'domain': [('demande_id', '=', self.id)],
                'context': {'default_demande_id': self.id}}


class KaRhCandidature(models.Model):
    """Candidature : pipeline par poste, de la réception à la décision ; la candidature retenue ouvre le dossier
    administratif du collaborateur sans ressaisie (§ 7.5.2-7.5.4)."""
    _name = 'ka.rh.candidature'
    _description = 'Candidature'
    _inherit = ['ka.document', 'mail.thread', 'mail.activity.mixin']
    _order = 'reference desc'

    reference = fields.Char(string='Référence', readonly=True, copy=False, default='Nouveau')
    name = fields.Char(string='Candidat', required=True)
    demande_id = fields.Many2one('ka.rh.demande.personnel', string='Demande de personnel', required=True,
                                 domain=[('state', 'in', ('approuvee', 'poste_ouvert'))])
    poste = fields.Char(related='demande_id.poste', string='Poste visé')
    affectation_id = fields.Many2one(related='demande_id.affectation_id', string='Affectation')
    email = fields.Char(string='Courriel')
    telephone = fields.Char(string='Téléphone')
    coordonnees = fields.Char(compute='_compute_coordonnees', string='Coordonnées')
    source = fields.Selection([('site', 'Site carrière'), ('spontanee', 'Candidature spontanée'),
                               ('cooptation', 'Cooptation'), ('courriel', 'Courriel')], string='Source de la candidature',
                              default='spontanee')
    cv = fields.Binary(string='CV et documents', attachment=True)
    cv_nom = fields.Char(string='Nom du CV')
    diplome = fields.Char(string='Diplôme / niveau')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    pretention = fields.Monetary(string='Prétention salariale (mensuelle)')
    pretention_txt = fields.Char(compute='_compute_coordonnees', string='Prétention salariale')
    entretien_date = fields.Datetime(string='Entretien planifié')
    evaluation_ids = fields.One2many('ka.rh.candidature.evaluation', 'candidature_id', string="Grille d'évaluation")
    prochaine_etape = fields.Text(string='Prochaine étape')
    motif_refus = fields.Char(string='Motif de refus')
    type_contrat = fields.Selection([('cdi', 'CDI'), ('cdd', 'CDD')], string='Type de contrat proposé')
    salaire_propose = fields.Monetary(string='Rémunération proposée')
    essai_mois = fields.Integer(string="Période d'essai (mois)")
    employe_id = fields.Many2one('ka.rh.employe', string='Dossier employé', readonly=True, copy=False)
    titre = fields.Char(compute='_compute_coordonnees')
    stage = fields.Selection(ETAPES, string='Étape', default='nouvelle', tracking=True, group_expand='_expand_stages')

    @api.depends('poste', 'name')
    def _compute_display_name(self):
        for c in self:
            c.display_name = '%s — %s' % (c.poste or '', c.name or '')

    def _ka_subtitle(self):
        self.ensure_one()
        return ' · '.join(x for x in (_('Poste : %s') % (self.poste or ''), self.affectation_id.name,
                                      _('Demande de personnel %s') % self.demande_id.name) if x)

    @api.model
    def _expand_stages(self, stages, domain):
        return [k for k, _l in ETAPES]

    @api.depends('email', 'telephone', 'pretention', 'name')
    def _compute_coordonnees(self):
        for c in self:
            c.coordonnees = ' · '.join(x for x in (c.email, c.telephone) if x)
            c.titre = _('Candidature — %s') % (c.name or '')
            c.pretention_txt = '%s FCFA / mois' % fcfa(c.pretention) if c.pretention else ''

    @api.constrains('demande_id')
    def _check_demande(self):
        for c in self:   # RG-7.6 : aucune candidature examinée sans demande de personnel approuvée
            if c.demande_id.state not in ('approuvee', 'poste_ouvert', 'pourvu'):
                raise ValidationError(_("La demande de personnel %s n'est pas approuvée (RG-7.6).") % c.demande_id.name)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', 'Nouveau') == 'Nouveau':
                vals['reference'] = self.env['ir.sequence'].next_by_code('ka.rh.candidature')
        recs = super().create(vals_list)
        for c in recs.filtered(lambda x: not x.evaluation_ids):
            c.evaluation_ids = [Command.create({'critere': k}) for k in
                                (_('Expérience technique'), _('Savoir-être'), _('Disponibilité'))]
        return recs

    def action_preselectionner(self):
        self.filtered(lambda c: c.stage == 'nouvelle').write({'stage': 'preselection'})

    def action_planifier_entretien(self):
        for c in self:
            if c.stage in ('recrutee', 'refusee'):
                raise UserError(_('La candidature est close.'))
            c.stage = 'entretien'
            c.activity_schedule('mail.mail_activity_data_meeting' if self.env.ref('mail.mail_activity_data_meeting', False)
                                else 'mail.mail_activity_data_todo', summary=_('Entretien — %s') % c.name,
                                date_deadline=(c.entretien_date and c.entretien_date.date()) or fields.Date.context_today(self),
                                user_id=self.env.user.id)

    def action_test(self):
        self.filtered(lambda c: c.stage == 'entretien').write({'stage': 'test'})

    def action_offre(self):
        for c in self:
            if c.stage not in ('entretien', 'test'):
                raise UserError(_("L'offre suit les entretiens (et le test éventuel)."))
            c.write({'stage': 'proposition', 'type_contrat': c.type_contrat or c.demande_id.type_contrat,
                     'salaire_propose': c.salaire_propose or c.demande_id.budget,
                     'essai_mois': c.essai_mois or c.demande_id.categorie_id.essai_mois})

    def action_refuser(self):
        for c in self:
            if not c.motif_refus:
                raise UserError(_('Un refus doit être motivé : renseignez le motif de refus.'))
            c.stage = 'refusee'

    def action_open_employe(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.rh.employe', 'res_id': self.employe_id.id, 'view_mode': 'form'}

    def action_recruter(self):
        """Bascule vers la prise de fonction : fiche employé créée à partir de la candidature (§ 7.5.4)."""
        for c in self:
            if c.stage != 'proposition':
                raise UserError(_("Faites d'abord une offre au candidat."))
            d = c.demande_id
            base = self.env['ka.rh.rubrique'].search([('categorie', '=', 'base')], limit=1)
            emp = self.env['ka.rh.employe'].create({
                'name': c.name, 'poste': d.poste, 'affectation_id': d.affectation_id.id, 'categorie_id': d.categorie_id.id,
                'type_contrat': c.type_contrat or d.type_contrat, 'essai_mois': c.essai_mois,
                'date_entree': d.date_souhaitee or fields.Date.context_today(self), 'telephone': c.telephone,
                'analytic_id': d.affectation_id.analytic_id.id,
                'element_ids': [Command.create({'rubrique_id': base.id, 'type': 'fixe_mensuel',
                                                'montant': c.salaire_propose})] if base and c.salaire_propose else []})
            c.write({'stage': 'recrutee', 'employe_id': emp.id})
            if len(d.candidature_ids.filtered(lambda x: x.stage == 'recrutee')) >= d.effectif:
                d.state = 'pourvu'
            emp.message_post(body=_("Dossier ouvert depuis la candidature %s : déclaration CNPS (formulaire D1) dans les "
                                    "huit jours, visite médicale d'embauche avant la fin de la période d'essai "
                                    "(RG-7.7), badge de pointage à attribuer.") % c.reference)
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.rh.employe', 'res_id': self[:1].employe_id.id,
                'view_mode': 'form'}


class KaRhCandidatureEvaluation(models.Model):
    """Grille d'entretien partagée : critère, note et commentaire de l'évaluateur."""
    _name = 'ka.rh.candidature.evaluation'
    _description = "Critère d'évaluation de candidature"
    _order = 'id'

    candidature_id = fields.Many2one('ka.rh.candidature', required=True, ondelete='cascade')
    critere = fields.Char(string='Critère', required=True)
    note = fields.Selection([('1', '1 / 5'), ('2', '2 / 5'), ('3', '3 / 5'), ('4', '4 / 5'), ('5', '5 / 5')], string='Note')
    commentaire = fields.Char(string='Commentaire')
