from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import mois_txt
from .param import NIVEAUX, RANG


class KaRhSession(models.Model):
    """Session de formation : organisme, dates, coût, éligibilité FDFP, participants et présence (§ 7.6.1-7.6.2).
    La clôture met à jour la compétence des participants dont le résultat est « validé » (RG-7.8)."""
    _name = 'ka.rh.session'
    _description = 'Session de formation'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'date_debut desc, name desc'

    name = fields.Char(string='N° session', readonly=True, copy=False, default='Nouveau')
    intitule = fields.Char(string='Intitulé', required=True)
    type = fields.Selection([('interne', 'Interne'), ('externe', 'Externe'), ('certifiante', 'Certifiante'),
                             ('securite', 'Sécurité'), ('habilitation', 'Habilitation')], string='Type de formation',
                            default='externe', required=True)
    organisme = fields.Char(string='Organisme')
    affectation_id = fields.Many2one('ka.rh.affectation', string='Atelier / service')
    origine = fields.Char(string='Origine du besoin', help='Plan de formation, entretien de carrière, obligation…')
    plan = fields.Char(string='Plan de formation', help='Ex. Plan de formation 2026')
    date_debut = fields.Date(string='Début', required=True)
    date_fin = fields.Date(string='Fin', required=True)
    duree = fields.Integer(compute='_compute_duree', string='Durée (jours)', store=True)
    dates_txt = fields.Char(compute='_compute_duree', string='Dates')
    lieu = fields.Char(string='Lieu')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    cout = fields.Monetary(string='Coût de la session')
    fdfp = fields.Selection([('non', 'Non'), ('ta', "Oui — Taxe d'apprentissage (0,4 %)"),
                             ('fpc', 'Oui — Formation professionnelle continue (1,2 %)')],
                            string='Éligible au financement FDFP', default='non')
    places = fields.Integer(string='Places', default=6)
    places_txt = fields.Char(compute='_compute_places', string='Places')
    competence_id = fields.Many2one('ka.rh.competence', string='Compétence visée')
    niveau_vise = fields.Selection(NIVEAUX, string='Niveau visé', default='acquis')
    participant_ids = fields.One2many('ka.rh.session.participant', 'session_id', string='Participants')
    info_txt = fields.Char(compute='_compute_places')
    state = fields.Selection([('planifiee', 'Planifiée'), ('en_cours', 'En cours'), ('terminee', 'Terminée'),
                              ('evaluee', 'Évaluée')], default='planifiee', string='Statut', tracking=True)

    @api.depends('name', 'intitule')
    def _compute_display_name(self):
        for s in self:
            s.display_name = '%s — %s' % (s.name, s.intitule or '')

    def _ka_subtitle(self):
        self.ensure_one()
        return ' · '.join(x for x in (_('Organisme : %s') % self.organisme if self.organisme else '',
                                      self.affectation_id.name) if x)

    @api.depends('date_debut', 'date_fin')
    def _compute_duree(self):
        for s in self:
            s.duree = (s.date_fin - s.date_debut).days + 1 if s.date_debut and s.date_fin and s.date_fin >= s.date_debut else 0
            if s.date_debut and s.date_fin:
                fmt = '%d' if (s.date_debut.month, s.date_debut.year) == (s.date_fin.month, s.date_fin.year) else '%d/%m/%Y'
                s.dates_txt = '%s → %s (%d jour%s)' % (s.date_debut.strftime(fmt), s.date_fin.strftime('%d/%m/%Y'),
                                                       s.duree, 's' if s.duree > 1 else '')
            else:
                s.dates_txt = ''

    @api.depends('participant_ids', 'places', 'competence_id', 'intitule')
    def _compute_places(self):
        for s in self:
            s.places_txt = _('%s / %s occupées') % (len(s.participant_ids), s.places)
            s.info_txt = _("À l'issue d'une formation validée, la compétence « %s » est automatiquement mise à jour sur la "
                           "fiche de chaque participant (§7.6.3, RG-7.8).") % (s.competence_id.name or s.intitule or '')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.rh.session')
        return super().create(vals_list)

    def action_demarrer(self):
        self.filtered(lambda s: s.state == 'planifiee').write({'state': 'en_cours'})

    def action_cloturer(self):
        """RG-7.8 : mise à jour automatique de la compétence des participants « validés » ; une session non achevée ou
        un résultat « non acquis » n'emporte aucune mise à jour."""
        for s in self:
            if s.state not in ('planifiee', 'en_cours'):
                raise UserError(_('La session est déjà clôturée.'))
            if s.participant_ids.filtered(lambda p: p.resultat == 'attente'):
                s.message_post(body=_('Résultats en attente : ces participants ne sont pas mis à jour.'))
            if s.competence_id:
                for p in s.participant_ids.filtered(lambda x: x.resultat == 'valide'):
                    p.employe_id.maj_competence(s.competence_id, s.niveau_vise, s.display_name)
            s.state = 'terminee'

    def action_evaluer(self):
        self.filtered(lambda s: s.state == 'terminee').write({'state': 'evaluee'})


class KaRhSessionParticipant(models.Model):
    _name = 'ka.rh.session.participant'
    _description = 'Participant à une session de formation'
    _order = 'id'

    session_id = fields.Many2one('ka.rh.session', required=True, ondelete='cascade')
    employe_id = fields.Many2one('ka.rh.employe', string='Employé', required=True)
    poste = fields.Char(related='employe_id.affectation_id.name', string='Poste')
    jours_presents = fields.Integer(string='Jours présents')
    presence = fields.Char(compute='_compute_presence', string='Présence')
    resultat = fields.Selection([('valide', 'Validé'), ('attente', 'En attente'), ('non_acquis', 'Non acquis')],
                                string='Résultat', default='attente')
    certificat = fields.Binary(string='Certificat / attestation', attachment=True)

    @api.depends('jours_presents', 'session_id.duree')
    def _compute_presence(self):
        for p in self:
            d = p.session_id.duree
            p.presence = (_('Présent (%s/%s j)') if p.jours_presents else _('Absent (%s/%s j)')) % (p.jours_presents, d)


class KaRhEmployeCompetence(models.Model):
    _inherit = 'ka.rh.employe'

    entretien_ids = fields.One2many('ka.rh.entretien', 'employe_id', string='Entretiens de carrière')

    def maj_competence(self, competence, niveau, origine):
        self.ensure_one()
        ligne = self.competence_ids.filtered(lambda c: c.competence_id == competence)
        vals = {'niveau': niveau, 'date': fields.Date.context_today(self), 'origine': origine}
        if ligne:
            if RANG.get(niveau, 0) >= RANG.get(ligne.niveau, 0):
                ligne.write(vals)
        else:
            self.write({'competence_ids': [Command.create(dict(vals, competence_id=competence.id))]})


class KaRhEntretien(models.Model):
    """Entretien de carrière : auto-évaluation, évaluation du responsable, compétences, objectifs (§ 7.6.3).
    Périodicité : 6 mois après la prise de fonction, 6 mois plus tard, puis annuelle (RG-7.9)."""
    _name = 'ka.rh.entretien'
    _description = 'Entretien de carrière'
    _inherit = ['ka.document', 'mail.thread', 'mail.activity.mixin']
    _order = 'date desc'

    employe_id = fields.Many2one('ka.rh.employe', string='Collaborateur', required=True)
    poste = fields.Char(related='employe_id.poste', string='Poste')
    type = fields.Selection([('six_mois', 'Entretien à six mois'), ('annuel', 'Entretien annuel')], string='Type',
                            default='annuel', required=True)
    date = fields.Date(string='Date prévue', required=True)
    anciennete_txt = fields.Char(related='employe_id.anciennete_txt', string='Ancienneté')
    dernier_txt = fields.Char(compute='_compute_dernier', string='Dernier entretien')
    evaluateur = fields.Char(string='Évaluateur')
    auto_evaluation = fields.Text(string='Auto-évaluation')
    evaluation = fields.Selection([('insuffisant', 'Insuffisant'), ('partiel', 'Atteint partiellement les attentes'),
                                   ('atteint', 'Atteint les attentes'), ('depasse', 'Dépasse les attentes')],
                                  string='Évaluation globale')
    ligne_ids = fields.One2many('ka.rh.entretien.ligne', 'entretien_id', string='Compétences évaluées')
    objectifs = fields.Text(string='Objectifs et plan de développement')
    prochaine_date = fields.Date(compute='_compute_prochaine', string='Prochain entretien', store=True)
    prochain_txt = fields.Char(compute='_compute_prochaine', string='Prochain entretien')
    titre = fields.Char(compute='_compute_titre')
    en_retard = fields.Boolean(compute='_compute_retard', string='Échu non réalisé', search='_search_retard')
    state = fields.Selection([('auto', 'Auto-évaluation'), ('manager', 'Entretien manager'), ('finalise', 'Finalisé')],
                             default='auto', string='Statut', tracking=True)

    @api.depends('employe_id', 'type', 'date')
    def _compute_display_name(self):
        for e in self:
            e.display_name = '%s — %s %s' % (e.employe_id.matricule or '', dict(self._fields['type'].selection)[e.type],
                                             e.date.year if e.date else '')

    def _ka_subtitle(self):
        self.ensure_one()
        return ' · '.join(x for x in (self.poste, self.employe_id.affectation_id.name,
                                      '%s — %s' % (dict(self._fields['type'].selection)[self.type], mois_txt(self.date)))
                          if x)

    @api.depends('employe_id')
    def _compute_titre(self):
        for e in self:
            e.titre = _('Entretien de carrière — %s') % (e.employe_id.matricule or '')

    def _compute_dernier(self):
        for e in self:
            prec = self.search([('employe_id', '=', e.employe_id.id), ('state', '=', 'finalise'), ('date', '<', e.date or
                                fields.Date.context_today(self))], order='date desc', limit=1)
            e.dernier_txt = mois_txt(prec.date) if prec else _('Aucun')

    @api.depends('date', 'employe_id.date_entree', 'type')
    def _compute_prochaine(self):
        for e in self:
            entree = e.employe_id.date_entree
            if not e.date or not entree:
                e.prochaine_date, e.prochain_txt = False, ''
                continue
            premiere_annee = e.date < entree + relativedelta(months=12)
            e.prochaine_date = e.date + relativedelta(months=6 if premiere_annee else 12)
            e.prochain_txt = _('Programmé le %s (%s, RG-7.9).') % (
                e.prochaine_date.strftime('%d/%m/%Y'),
                _('second entretien six mois plus tard') if premiere_annee else
                _('périodicité annuelle après la première année de suivi'))

    def _compute_retard(self):
        today = fields.Date.context_today(self)
        for e in self:
            e.en_retard = e.state != 'finalise' and e.date and e.date < today

    def _search_retard(self, operator, value):
        # Odoo 19 normalise les conditions booléennes en ('in', [True]) / ('not in', [True])
        if operator not in ('in', 'not in'):
            return NotImplemented
        today = fields.Date.context_today(self)
        vrai = [('state', '!=', 'finalise'), ('date', '<', today)]
        return vrai if operator == 'in' else ['|', ('state', '=', 'finalise'), ('date', '>=', today)]

    @api.onchange('employe_id')
    def _onchange_employe(self):
        if self.employe_id and not self.ligne_ids:
            self.ligne_ids = [Command.create({'competence_id': c.competence_id.id, 'niveau_precedent': c.niveau,
                                              'niveau_actuel': c.niveau}) for c in self.employe_id.competence_ids]
            self.evaluateur = self.employe_id.responsable

    def action_entretien_manager(self):
        self.filtered(lambda e: e.state == 'auto').write({'state': 'manager'})

    def action_finaliser(self):
        for e in self:
            if not e.evaluation:
                raise UserError(_("Renseignez l'évaluation globale."))
            for l in e.ligne_ids.filtered('niveau_actuel'):
                e.employe_id.maj_competence(l.competence_id, l.niveau_actuel, e.display_name)
            e.state = 'finalise'
            e.activity_ids.action_feedback(feedback=_('Finalisé'))
            if e.prochaine_date and not self.search_count([('employe_id', '=', e.employe_id.id), ('date', '>', e.date)]):
                self.create({'employe_id': e.employe_id.id, 'date': e.prochaine_date, 'evaluateur': e.evaluateur,
                             'type': 'six_mois' if e.prochaine_date < e.employe_id.date_entree + relativedelta(months=12)
                             else 'annuel'})

    @api.model
    def _cron_entretiens(self):
        """Génère le premier entretien (6 mois après l'entrée) et signale les entretiens échus non réalisés (RG-7.9)."""
        for emp in self.env['ka.rh.employe'].search([('state', '=', 'actif')]):
            if not self.search_count([('employe_id', '=', emp.id)]):
                self.create({'employe_id': emp.id, 'type': 'six_mois', 'evaluateur': emp.responsable,
                             'date': emp.date_entree + relativedelta(months=6)})
        for e in self.search([('en_retard', '=', True)]):
            if not e.activity_ids:
                e.activity_schedule('mail.mail_activity_data_todo', summary=_('Entretien de carrière échu non réalisé'),
                                    user_id=self.env.user.id)


class KaRhEntretienLigne(models.Model):
    _name = 'ka.rh.entretien.ligne'
    _description = "Compétence évaluée en entretien"
    _order = 'id'

    entretien_id = fields.Many2one('ka.rh.entretien', required=True, ondelete='cascade')
    competence_id = fields.Many2one('ka.rh.competence', string='Compétence', required=True)
    niveau_precedent = fields.Selection(NIVEAUX, string='Niveau précédent')
    niveau_actuel = fields.Selection(NIVEAUX, string='Niveau actuel')
    evolution = fields.Char(compute='_compute_evolution', string='Évolution')
    tendance = fields.Selection([('up', 'Hausse'), ('down', 'Baisse'), ('stable', 'Stable')], compute='_compute_evolution')

    @api.depends('niveau_precedent', 'niveau_actuel')
    def _compute_evolution(self):
        for l in self:
            l.tendance = 'up' if (not l.niveau_precedent and l.niveau_actuel) or RANG.get(l.niveau_actuel, 0) > RANG.get(
                l.niveau_precedent, 0) else ('down' if RANG.get(l.niveau_actuel, 0) < RANG.get(l.niveau_precedent, 0) else 'stable')
            if not l.niveau_precedent and l.niveau_actuel:
                l.evolution = _('↑ Nouvelle compétence')
            elif RANG.get(l.niveau_actuel, 0) > RANG.get(l.niveau_precedent, 0):
                l.evolution = _('↑ Progression')
            elif RANG.get(l.niveau_actuel, 0) < RANG.get(l.niveau_precedent, 0):
                l.evolution = _('↓ Régression')
            else:
                l.evolution = _('= Stable')
