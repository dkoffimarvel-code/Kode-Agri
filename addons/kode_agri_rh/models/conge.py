from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PLAFOND_PERMISSION = 10   # jours par an, paramètre kode_agri_rh.plafond_permission (RG-7.3)
MALADIE = [  # ancienneté minimale (mois), libellé, maintien à plein salaire (jours), à demi-salaire (jours) — § 7.2.3
    (0, "Moins d'un mois", '5 jours à plein salaire', 5, 0),
    (1, 'De 1 à 5 ans', '1 mois plein, puis 2 mois à demi-salaire', 30, 60),
    (60, 'Plus de 5 ans', '2 mois plein, puis 4 mois à demi-salaire', 60, 120),
]


class KaRhDemande(models.Model):
    """Demande de congé payé, de permission ou d'absence : circuit commun de soumission et de validation (§ 7.2.5).
    L'approbation met à jour le solde de congés, bloque le planning de présence et alimente la paie du mois."""
    _name = 'ka.rh.demande'
    _description = 'Demande de congé, de permission ou d\'absence'
    _inherit = ['ka.document', 'mail.thread', 'mail.activity.mixin']
    _order = 'date_debut desc, id desc'

    name = fields.Char(string='N° demande', readonly=True, copy=False, default='Nouveau')
    type_demande = fields.Selection([('conge', 'Demande de congé payé'), ('permission', 'Demande de permission'),
                                     ('absence', "Demande d'absence")], string='Type de demande', required=True,
                                    default='conge')
    employe_id = fields.Many2one('ka.rh.employe', string='Employé', required=True)
    type_conge_id = fields.Many2one('ka.rh.type.conge', string='Type de congé')
    motif = fields.Selection([('maladie', 'Maladie'), ('evenement', 'Événement personnel'),
                              ('force_majeure', 'Force majeure'), ('non_justifiee', 'Absence non justifiée')],
                             string='Motif')
    evenement = fields.Selection([('mariage', 'Mariage'), ('naissance', 'Naissance'), ('deces', 'Décès')],
                                 string='Événement familial')
    foyer = fields.Boolean(string='Concerne le foyer du collaborateur', default=True)
    date_debut = fields.Date(string='Début', required=True)
    date_fin = fields.Date(string='Fin', required=True)
    duree = fields.Float(compute='_compute_duree', string='Durée (jours ouvrables)', store=True, digits=(5, 1))
    duree_txt = fields.Char(compute='_compute_duree', string='Durée')
    justificatif = fields.Binary(string='Justificatif', attachment=True)
    justificatif_nom = fields.Char(string='Nom du justificatif')
    delai = fields.Selection([('48h', 'Reçu sous 48 h'), ('72h', 'Reçu sous 72 h'), ('hors_delai', 'Hors délai')],
                             string='Délai de transmission')
    responsable = fields.Char(related='employe_id.responsable', string='Responsable à valider')
    second_valideur = fields.Boolean(string='Validation RH requise', compute='_compute_valideurs')
    valide_hierarchie = fields.Boolean(string='Approuvée par le responsable', readonly=True, copy=False)
    solde_disponible = fields.Float(compute='_compute_solde', string='Solde disponible', digits=(5, 1))
    solde_apres = fields.Float(compute='_compute_solde', string='Solde après validation', digits=(5, 1))
    jours_non_remuneres = fields.Float(compute='_compute_solde', string='Jours non rémunérés', store=True, digits=(5, 1))
    anciennete_txt = fields.Char(related='employe_id.anciennete_txt', string='Ancienneté du collaborateur')
    bareme_html = fields.Html(compute='_compute_bareme', sanitize=False)
    effet_txt = fields.Char(compute='_compute_bareme', string='Effet sur le solde de congés')
    solde_html = fields.Html(compute='_compute_solde_html', sanitize=False)
    paie_traitement = fields.Selection([('integral', 'Maintien intégral'), ('partiel', 'Maintien partiel'),
                                        ('retenue', 'Retenue sur salaire')], compute='_compute_bareme',
                                       string='Traitement en paie', store=True)
    titre = fields.Char(compute='_compute_titre')
    tag = fields.Char(compute='_compute_titre')
    solde_titre = fields.Char(compute='_compute_titre')
    state = fields.Selection([('brouillon', 'Brouillon'), ('a_approuver', 'À approuver'), ('approuvee', 'Approuvée'),
                              ('refusee', 'Refusée')], default='brouillon', string='Statut', tracking=True)

    @api.depends('name', 'type_demande')
    def _compute_display_name(self):
        nouveau = {'conge': _('Nouvelle demande'), 'permission': _('Nouvelle permission'), 'absence': _('Nouvelle absence')}
        for d in self:
            d.display_name = '%s — %s' % (d.name, nouveau[d.type_demande] if d.state == 'brouillon' else
                                          dict(self._fields['state'].selection)[d.state])

    def _ka_subtitle(self):
        self.ensure_one()
        e = self.employe_id
        return ' · '.join(x for x in (e.matricule, e.poste, e.affectation_id.name) if x)

    @api.depends('type_demande', 'type_conge_id', 'motif', 'evenement', 'employe_id')
    def _compute_titre(self):
        motifs = dict(self._fields['motif'].selection)
        evts = dict(self._fields['evenement'].selection)
        for d in self:
            d.titre = dict(self._fields['type_demande'].selection)[d.type_demande]
            d.tag = (d.type_conge_id.name or '').replace(' payé', '') if d.type_demande == 'conge' else (
                motifs.get(d.motif, '') if d.type_demande == 'absence' else evts.get(d.evenement, ''))
            d.solde_titre = _('Solde de congés — %s') % (d.employe_id.matricule or '')

    @api.depends('date_debut', 'date_fin')
    def _compute_duree(self):
        feries = set(self.env['ka.rh.ferie'].search([]).mapped('date'))
        for d in self:
            n = 0
            if d.date_debut and d.date_fin and d.date_fin >= d.date_debut:
                jour = d.date_debut
                while jour <= d.date_fin:
                    if jour.weekday() < 5 and jour not in feries:   # jours fériés exclus du décompte (§ 7.2.4)
                        n += 1
                    jour += timedelta(days=1)
            d.duree = n
            d.duree_txt = (_('%s jours ouvrables') if d.type_demande == 'conge' else _('%s jours')) % (
                ('%g' % n).replace('.', ','))

    @api.depends('type_demande')
    def _compute_valideurs(self):
        for d in self:   # circuit à deux niveaux pour les absences et permissions (service RH)
            d.second_valideur = d.type_demande in ('absence', 'permission')

    @api.depends('employe_id', 'type_conge_id', 'duree', 'type_demande', 'evenement', 'foyer', 'date_debut')
    def _compute_solde(self):
        plafond = float(self.env['ir.config_parameter'].sudo().get_param('kode_agri_rh.plafond_permission', PLAFOND_PERMISSION))
        for d in self:
            solde = d.employe_id.solde_ids.filtered(lambda s: s.type_id == d.type_conge_id)[:1]
            d.solde_disponible = solde.solde
            deduit = d.duree if d.type_demande == 'conge' and d.type_conge_id.deductible else 0.0
            d.solde_apres = solde.solde - deduit
            nr = 0.0
            if d.type_demande == 'permission':   # RG-7.3 : plafond annuel, hors foyer non rémunérée
                if not d.foyer:
                    nr = d.duree
                elif d.date_debut and d.employe_id:
                    deja = sum(self.search([('employe_id', '=', d.employe_id.id), ('type_demande', '=', 'permission'),
                                            ('state', '=', 'approuvee'), ('foyer', '=', True), ('id', '!=', d._origin.id),
                                            ('date_debut', '>=', d.date_debut.replace(month=1, day=1))]).mapped('duree'))
                    nr = max(deja + d.duree - plafond, 0.0) if deja + d.duree > plafond else 0.0
                    nr = min(nr, d.duree)
            elif d.type_demande == 'absence' and d.motif == 'non_justifiee':
                nr = d.duree
            elif d.type_demande == 'conge' and d.type_conge_id and not d.type_conge_id.remunere:
                nr = d.duree
            d.jours_non_remuneres = nr

    @api.depends('type_demande', 'motif', 'employe_id', 'type_conge_id')
    def _compute_bareme(self):
        for d in self:
            mois = d.employe_id.anciennete_mois
            if d.type_demande == 'absence':
                if d.motif == 'maladie':
                    applicable = [b for b in MALADIE if mois >= b[0]][-1]
                    lignes = ''.join('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                        b[1], b[2], '<span class="o_ka_ok_txt">Cas du collaborateur</span>' if b == applicable else '—')
                        for b in MALADIE)
                    d.bareme_html = ('<table class="o_ka_tbl"><thead><tr><th>Ancienneté</th><th>Maintien de salaire</th>'
                                     '<th>Application au dossier</th></tr></thead><tbody>%s</tbody></table>' % lignes)
                    d.paie_traitement = 'integral'
                    d.effet_txt = _("Cette absence n'est pas déduite du solde de congés payés. Elle est assimilée à du "
                                    "temps de travail effectif pour l'acquisition des congés, dans la limite de six mois "
                                    "(§7.2.3).")
                else:
                    d.bareme_html = False
                    d.paie_traitement = 'retenue' if d.motif == 'non_justifiee' else 'integral'
                    d.effet_txt = _("Absence non déductible du congé payé ; traitement en paie : %s.") % (
                        _('retenue sur salaire') if d.motif == 'non_justifiee' else _('maintien du salaire'))
            elif d.type_demande == 'permission':
                d.bareme_html = False
                d.paie_traitement = 'integral' if d.foyer else 'retenue'
                d.effet_txt = _("Permission non déductible du congé payé, rémunérée dans la limite de %s jours par an pour "
                                "un événement touchant le foyer (RG-7.3).") % PLAFOND_PERMISSION
            else:
                d.bareme_html = False
                d.paie_traitement = 'integral' if d.type_conge_id.remunere or not d.type_conge_id else 'retenue'
                d.effet_txt = False

    @api.depends('employe_id.solde_ids.acquis', 'employe_id.solde_ids.pris')
    def _compute_solde_html(self):
        for d in self:
            lignes = ''.join('<tr><td>%s</td><td class="o_ka_num">%s</td><td class="o_ka_num">%s</td>'
                             '<td class="o_ka_num">%s</td></tr>' % (s.type_id.name, _n(s.acquis), _n(s.pris), _n(s.solde))
                             for s in d.employe_id.solde_ids)
            d.solde_html = ('<table class="o_ka_tbl"><thead><tr><th>Type de congé</th><th class="o_ka_num">Acquis</th>'
                            '<th class="o_ka_num">Pris</th><th class="o_ka_num">Solde</th></tr></thead><tbody>%s</tbody>'
                            '</table>' % lignes) if lignes else False

    @api.constrains('date_debut', 'date_fin')
    def _check_dates(self):
        for d in self:
            if d.date_fin < d.date_debut:
                raise ValidationError(_('La date de fin précède la date de début.'))

    @api.model_create_multi
    def create(self, vals_list):
        prefixes = {'conge': 'ka.rh.conge', 'permission': 'ka.rh.permission', 'absence': 'ka.rh.absence'}
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code(prefixes[vals.get('type_demande', 'conge')])
        return super().create(vals_list)

    # ---- circuit ------------------------------------------------------------------------------------------------
    def action_soumettre(self):
        for d in self:
            if d.state != 'brouillon':
                continue
            if d.type_demande == 'conge':
                if not d.type_conge_id:
                    raise UserError(_('Précisez le type de congé.'))
                if d.type_conge_id.code == 'CA' and d.employe_id.anciennete_mois < 12:   # RG-7.2
                    raise UserError(_("Le congé annuel ne peut être pris qu'après douze mois de travail effectif "
                                      "(RG-7.2)."))
                if d.type_conge_id.deductible and d.duree > d.solde_disponible:
                    raise UserError(_('Solde insuffisant : %s jours disponibles pour %s demandés.') % (
                        _n(d.solde_disponible), _n(d.duree)))
            if d.type_demande == 'absence':
                if not d.motif:
                    raise UserError(_("Précisez le motif de l'absence."))
                if d.motif == 'maladie' and not d.justificatif:
                    raise UserError(_('Le certificat médical est obligatoire pour une absence pour maladie.'))
            if d.type_demande == 'permission' and not d.evenement:
                raise UserError(_("Précisez l'événement familial."))
            d.state = 'a_approuver'
            d.activity_schedule('mail.mail_activity_data_todo', summary=_('%s à approuver') % d.name,
                                user_id=self.env.user.id)

    def action_approuver(self):
        for d in self.filtered(lambda x: x.state == 'a_approuver'):
            if d.second_valideur and not d.valide_hierarchie:
                d.valide_hierarchie = True   # premier niveau : responsable hiérarchique ; le service RH valide ensuite
                d.message_post(body=_('Approuvée par le responsable hiérarchique ; en attente du service RH.'))
                continue
            d.valide_hierarchie = True
            if d.type_demande == 'conge' and d.type_conge_id.deductible:
                solde = d.employe_id.solde_ids.filtered(lambda s: s.type_id == d.type_conge_id)[:1]
                if not solde:
                    solde = self.env['ka.rh.solde'].create({'employe_id': d.employe_id.id, 'type_id': d.type_conge_id.id})
                solde.pris += d.duree
            d.state = 'approuvee'
            d.activity_ids.action_feedback(feedback=_('Approuvée'))

    def action_refuser(self):
        for d in self.filtered(lambda x: x.state == 'a_approuver'):
            d.state = 'refusee'
            d.activity_ids.unlink()

    def action_brouillon(self):
        self.filtered(lambda x: x.state == 'refusee').write({'state': 'brouillon', 'valide_hierarchie': False})

    @api.model
    def couvre(self, employe, jour):
        """Vrai si une demande approuvée couvre ce jour (le planning de présence est bloqué)."""
        return bool(self.search_count([('employe_id', '=', employe.id), ('state', '=', 'approuvee'),
                                       ('date_debut', '<=', jour), ('date_fin', '>=', jour)]))


def _n(x):
    return ('%.1f' % (x or 0.0)).replace('.', ',')


class KaRhSolde(models.Model):
    """Solde de congés d'un collaborateur par type : jours acquis, pris et solde disponible (§ 7.2.4)."""
    _name = 'ka.rh.solde'
    _description = 'Solde de congés'
    _order = 'employe_id, type_id'

    employe_id = fields.Many2one('ka.rh.employe', string='Employé', required=True, ondelete='cascade')
    type_id = fields.Many2one('ka.rh.type.conge', string='Type de congé', required=True)
    acquis = fields.Float(string='Acquis', digits=(6, 1))
    pris = fields.Float(string='Pris', digits=(6, 1))
    solde = fields.Float(compute='_compute_solde', string='Solde', store=True, digits=(6, 1))
    derniere_acquisition = fields.Date(string='Dernière acquisition')

    @api.depends('acquis', 'pris')
    def _compute_solde(self):
        for s in self:
            s.solde = s.acquis - s.pris

    @api.model
    def _cron_acquisition(self):
        """Acquisition mensuelle au prorata du travail effectif (ex. 2,2 jours ouvrables par mois)."""
        today = fields.Date.context_today(self)
        debut_mois = today.replace(day=1)
        for e in self.env['ka.rh.employe'].search([('state', '=', 'actif')]):
            e._init_soldes()
            for s in e.solde_ids.filtered(lambda x: x.type_id.acquisition and
                                          (not x.derniere_acquisition or x.derniere_acquisition < debut_mois)):
                non_remunere = sum(self.env['ka.rh.demande'].search([
                    ('employe_id', '=', e.id), ('state', '=', 'approuvee'), ('jours_non_remuneres', '>', 0),
                    ('date_debut', '>=', debut_mois - timedelta(days=31)), ('date_debut', '<', debut_mois)]).mapped(
                    'jours_non_remuneres'))
                prorata = max(0.0, 1 - non_remunere / 22.0)   # absences non assimilées : prorata du travail effectif
                s.write({'acquis': s.acquis + s.type_id.acquisition * prorata, 'derniere_acquisition': debut_mois})
