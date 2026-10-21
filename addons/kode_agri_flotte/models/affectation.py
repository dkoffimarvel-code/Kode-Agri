from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.kode_agri_maintenance.models.equipement import nb

MISSIONS = [('collecte', 'Collecte fond de tasse'), ('livraison_interne', 'Livraison interne'),
            ('transfert_port', 'Transfert port'), ('autre', 'Autre')]


class KaFloAffectation(models.Model):
    """Affectation d'un conducteur et d'un véhicule à une mission (§ 11.5) : tournée de collecte, livraison interne,
    transfert vers le port. Camion en propre : la clôture permet de générer l'ordre de mission du conducteur (RG-11.6) ;
    prestataire externe : la tournée suit le circuit achats et sa clôture déclenche la réception (RG-11.4)."""
    _name = 'ka.flo.affectation'
    _description = 'Affectation conducteur / mission'
    _inherit = ['ka.document', 'ka.flo.achat', 'mail.thread', 'mail.activity.mixin']
    _order = 'date desc, name desc'

    name = fields.Char(string='N° affectation', readonly=True, copy=False, default='Nouveau')
    mode = fields.Selection([('propre', 'Camion en propre'), ('prestataire', 'Prestataire externe')],
                            string='Mode de réalisation', required=True, default='propre')
    vehicule_id = fields.Many2one('ka.flo.vehicule', string='Véhicule', required=True)
    vehicule_txt = fields.Char(compute='_compute_txt', string='Véhicule')
    conducteur_id = fields.Many2one('ka.rh.employe', string='Conducteur')
    conducteur_nom = fields.Char(related='conducteur_id.name', string='Conducteur')
    type_mission = fields.Selection(MISSIONS, string='Type de mission', required=True, default='collecte')
    itineraire = fields.Char(string='Zone / itinéraire', help='Ex. Zone Sud — 4 points de collecte')
    zone_id = fields.Many2one('account.analytic.account', string='Zone de collecte (analytique)')
    voyage_id = fields.Many2one('ka.voyage', string='Ordre de voyage (module 5)')
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    depart_prevu = fields.Datetime(string='Départ prévu')
    retour_prevu = fields.Datetime(string='Retour prévu')
    depart_reel = fields.Datetime(string='Départ réel', readonly=True, copy=False)
    retour_reel = fields.Datetime(string='Retour réel', readonly=True, copy=False)
    horaires_txt = fields.Char(compute='_compute_txt', string='Départ / retour réels')
    km_depart = fields.Float(string='Km au départ', digits=(12, 0))
    km_retour = fields.Float(string='Km au retour', digits=(12, 0))
    distance = fields.Float(compute='_compute_txt', string='Distance parcourue', store=True, digits=(12, 0))
    distance_txt = fields.Char(compute='_compute_txt', string='Distance parcourue')
    duree_txt = fields.Char(compute='_compute_txt', string='Durée réelle')
    mission_id = fields.Many2one('ka.rh.mission', string='Ordre de mission', readonly=True, copy=False)
    mission_txt = fields.Char(compute='_compute_txt', string='Ordre de mission')
    incident_ids = fields.One2many('ka.flo.incident', 'affectation_id', string='Incidents')
    incident_txt = fields.Char(compute='_compute_txt', string='Incidents')
    historique_ids = fields.Many2many('ka.flo.affectation', compute='_compute_historique', string='Historique des affectations récentes')
    titre = fields.Char(compute='_compute_txt')
    state = fields.Selection([('planifiee', 'Planifiée'), ('en_cours', 'En cours'), ('terminee', 'Terminée')],
                             default='planifiee', string='Statut', tracking=True)

    @api.depends('name', 'vehicule_id')
    def _compute_display_name(self):
        for a in self:
            a.display_name = '%s — %s' % (a.name, a.vehicule_id.name or '')

    def _ka_subtitle(self):
        self.ensure_one()
        tournee = {'collecte': _('Tournée collecte fond de tasse'), 'livraison_interne': _('Livraison interne'),
                   'transfert_port': _('Transfert port'), 'autre': _('Mission')}[self.type_mission or 'autre']
        qui = self.conducteur_id.name if self.mode == 'propre' else (self.prestataire_id.name or _('Prestataire externe'))
        return ' · '.join(x for x in (self.vehicule_id.name, qui, tournee) if x)

    @api.depends('km_depart', 'km_retour', 'depart_reel', 'retour_reel', 'vehicule_id', 'mission_id', 'incident_ids', 'name')
    def _compute_txt(self):
        for a in self:
            a.titre = _('Affectation %s') % (a.name or '')
            a.vehicule_txt = ' · '.join(x for x in (a.vehicule_id.name, a.vehicule_id.libelle) if x)
            a.distance = max(a.km_retour - a.km_depart, 0.0) if a.km_retour else 0.0
            a.distance_txt = nb(a.distance, a.vehicule_id.unite_compteur or 'km')
            if a.depart_reel:
                d = fields.Datetime.context_timestamp(a, a.depart_reel)
                r = fields.Datetime.context_timestamp(a, a.retour_reel) if a.retour_reel else False
                a.horaires_txt = '%s → %s' % (d.strftime('%H:%M'), r.strftime('%H:%M') if r else '…')
            else:
                a.horaires_txt = ''
            if a.depart_reel and a.retour_reel:
                m = int((a.retour_reel - a.depart_reel).total_seconds() // 60)
                a.duree_txt = '%d h %02d' % (m // 60, m % 60)
            else:
                a.duree_txt = '—'
            a.mission_txt = '%s · RH & Paie' % a.mission_id.name if a.mission_id else ''
            n = len(a.incident_ids)
            a.incident_txt = (_("Aucun incident signalé sur cette affectation. Tout accident ou sinistre déclaré est rattaché "
                                "au véhicule et au conducteur (§ 11.5).") if not n else
                              _('%d incident(s) déclaré(s), rattaché(s) au véhicule et au conducteur (§ 11.5).') % n)

    def _compute_historique(self):
        for a in self:
            a.historique_ids = self.search([('vehicule_id', '=', a.vehicule_id.id), ('id', '!=', a._origin.id)],
                                           order='date desc', limit=5) if a.vehicule_id else self.browse()

    @api.onchange('vehicule_id')
    def _onchange_vehicule(self):
        if self.vehicule_id:
            self.conducteur_id = self.conducteur_id or self.vehicule_id.conducteur_id
            self.km_depart = self.vehicule_id.odometre
            self.zone_id = self.zone_id or self.vehicule_id.zone_id

    @api.onchange('mode')
    def _onchange_mode(self):
        self.externe = self.mode == 'prestataire'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.flo.affectation')
            vals['externe'] = vals.get('mode') == 'prestataire'
        return super().create(vals_list)

    def action_planifier(self):
        """Contrôles d'affectation : documents à jour (§ 11.4) ; tournée externe : circuit achats (RG-11.4)."""
        for a in self:
            if a.mode == 'propre':
                if not a.conducteur_id:
                    raise UserError(_('Affectez un conducteur.'))
                a.vehicule_id.verifier_disponibilite()
            elif not a.commande_id and not a.da_id:
                a._ka_lancer_achat(_('Tournée %s — %s') % (a.name, a.itineraire or ''), 0.0)
            a.message_post(body=_('Affectation planifiée.'))

    def action_demarrer(self):
        """RG-11.5 : un véhicule et un conducteur ne sont engagés que sur une seule affectation active à la fois."""
        for a in self:
            if a.state != 'planifiee':
                raise UserError(_("L'affectation n'est pas planifiée."))
            if a.mode == 'propre':
                a.vehicule_id.verifier_disponibilite()
                conflit = self.search([('id', '!=', a.id), ('state', '=', 'en_cours'), '|',
                                       ('vehicule_id', '=', a.vehicule_id.id), ('conducteur_id', '=', a.conducteur_id.id)], limit=1)
                if conflit:
                    raise UserError(_('Le véhicule ou le conducteur est déjà mobilisé sur %s (RG-11.5).') % conflit.name)
                a.vehicule_id.state = 'en_mission'
            a.write({'state': 'en_cours', 'depart_reel': fields.Datetime.now(), 'km_depart': a.km_depart or a.vehicule_id.odometre})

    def action_terminer(self):
        for a in self:
            if a.state != 'en_cours':
                raise UserError(_("Seule une affectation en cours peut être terminée."))
            if a.mode == 'propre' and a.km_retour and a.km_retour < a.km_depart:
                raise UserError(_('Le kilométrage au retour est inférieur au kilométrage au départ.'))
            a._ka_controler_commande()   # tournée externe : clôture (ordre de voyage) conditionnée à la commande approuvée
            a._ka_reception_auto(a.name)
            a.write({'state': 'terminee', 'retour_reel': fields.Datetime.now()})
            if a.mode == 'propre':
                a.vehicule_id.maj_compteur(a.km_retour, a.name, a.date)
                if a.vehicule_id.state == 'en_mission':
                    a.vehicule_id.state = 'disponible'

    def action_mission(self):
        """RG-11.6 : ordre de mission du conducteur (camion en propre, affectation terminée), transmis au module RH et
        Paie (module 7) pour le calcul des indemnités ; un seul ordre par affectation clôturée."""
        self.ensure_one()
        if self.mode != 'propre' or self.state != 'terminee':
            raise UserError(_("Le bouton Mission n'est actif qu'une fois la tournée terminée, pour un camion en propre (RG-11.6)."))
        if self.mission_id:
            raise UserError(_("L'ordre de mission %s a déjà été généré pour cette affectation.") % self.mission_id.name)
        jour = self.date
        mission = self.env['ka.rh.mission'].create({
            'employe_id': self.conducteur_id.id, 'objet': dict(MISSIONS)[self.type_mission],
            'titre_court': _('Tournée %s') % (self.itineraire or ''), 'destination': self.itineraire,
            'date_debut': jour, 'date_fin': jour, 'moyen_transport': 'vehicule', 'vehicule_id': self.vehicule_id.id,
            'affectation_id': self.id, 'analytic_id': self.zone_id.id or False})
        mission.action_soumettre()
        mission.message_post(body=_('Ordre de mission généré depuis l\'affectation %s : véhicule %s, %s parcourus, '
                                    'départ / retour %s.') % (self.name, self.vehicule_id.name, self.distance_txt, self.horaires_txt))
        self.mission_id = mission
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.rh.mission', 'res_id': mission.id, 'view_mode': 'form'}

    def action_open_vehicule(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.flo.vehicule', 'res_id': self.vehicule_id.id, 'view_mode': 'form'}

    def action_declarer_incident(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Déclarer un incident'), 'res_model': 'ka.flo.incident',
                'view_mode': 'form', 'target': 'new', 'context': {'default_affectation_id': self.id}}


class KaFloIncident(models.Model):
    """Accident ou sinistre, rattaché à l'affectation, au véhicule et au conducteur (RG-11.5)."""
    _name = 'ka.flo.incident'
    _description = 'Incident de flotte'
    _order = 'date desc'

    affectation_id = fields.Many2one('ka.flo.affectation', string='Affectation', ondelete='cascade')
    vehicule_id = fields.Many2one('ka.flo.vehicule', string='Véhicule', compute='_compute_liens', store=True, readonly=False)
    conducteur_id = fields.Many2one('ka.rh.employe', string='Conducteur', compute='_compute_liens', store=True, readonly=False)
    date = fields.Datetime(string='Date', required=True, default=fields.Datetime.now)
    type = fields.Selection([('accident', 'Accident'), ('sinistre', 'Sinistre'), ('panne', 'Panne en route'), ('autre', 'Autre')],
                            string='Type', required=True, default='accident')
    description = fields.Text(string='Description', required=True)
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    cout_estime = fields.Monetary(string='Coût estimé')

    @api.depends('affectation_id')
    def _compute_liens(self):
        for i in self:
            if i.affectation_id:
                i.vehicule_id, i.conducteur_id = i.affectation_id.vehicule_id, i.affectation_id.conducteur_id


class KaRhMissionVehicule(models.Model):
    """Ordre de mission (module 7) : véhicule de service de la flotte et affectation d'origine."""
    _inherit = 'ka.rh.mission'

    vehicule_id = fields.Many2one('ka.flo.vehicule', string='Véhicule de service (module 11)')
    affectation_id = fields.Many2one('ka.flo.affectation', string='Affectation', readonly=True)

    @api.onchange('vehicule_id')
    def _onchange_vehicule_flotte(self):
        if self.vehicule_id:
            self.vehicule_txt = '%s — %s (module 11)' % (dict(self.vehicule_id._fields['type'].selection).get(self.vehicule_id.type), self.vehicule_id.name)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('vehicule_id') and not vals.get('vehicule_txt'):
                v = self.env['ka.flo.vehicule'].browse(vals['vehicule_id'])
                vals['vehicule_txt'] = '%s — %s (module 11)' % (dict(v._fields['type'].selection).get(v.type), v.name)
        return super().create(vals_list)
