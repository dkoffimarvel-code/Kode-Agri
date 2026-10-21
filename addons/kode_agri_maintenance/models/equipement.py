from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

HEURES_REQUISES_JOUR = 16.0   # temps requis de l'outil industriel (deux postes), base de la disponibilité
CRITICITE = [('critique', 'Critique'), ('important', 'Important'), ('secondaire', 'Secondaire')]


def nb(x, unite=''):
    return ('{:,.0f}'.format(x or 0).replace(',', ' ')) + (' ' + unite if unite else '')


class KaMntEquipe(models.Model):
    """Équipe de maintenance : techniciens et taux horaire de cession interne de la main-d'œuvre."""
    _name = 'ka.mnt.equipe'
    _description = 'Équipe de maintenance'

    name = fields.Char(string='Équipe', required=True)
    technicien_ids = fields.Many2many('ka.rh.employe', string='Techniciens')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    taux_horaire = fields.Monetary(string='Taux horaire de main-d\'œuvre', help='Valorisation des temps passés sur les OT')


class KaMntEquipement(models.Model):
    """Fiche machine (§ 10.1) : identité technique, rattachement au poste de charge (module 4) et à l'immobilisation
    (module 3), compteurs, criticité ; arborescence site → atelier → ligne → machine → sous-ensemble."""
    _name = 'ka.mnt.equipement'
    _description = 'Équipement'
    _inherit = ['ka.document', 'mail.thread', 'mail.activity.mixin']
    _parent_store = True
    _order = 'complete_code'

    code = fields.Char(string='Code équipement', required=True, copy=False)
    name = fields.Char(string='Nom', required=True, help='Ex. Séchoir n°2')
    designation = fields.Char(string='Désignation', required=True, help='Ex. Séchoir tunnel n°2')
    niveau = fields.Selection([('site', 'Site'), ('atelier', 'Atelier'), ('ligne', 'Ligne'), ('machine', 'Machine'),
                               ('sous_ensemble', 'Sous-ensemble')], string='Niveau', default='machine', required=True)
    parent_id = fields.Many2one('ka.mnt.equipement', string='Rattaché à', index=True, ondelete='restrict')
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('ka.mnt.equipement', 'parent_id', string='Sous-ensembles')
    complete_code = fields.Char(compute='_compute_complete', store=True, recursive=True)
    atelier = fields.Char(string='Atelier', required=True, help='Ex. Séchage')
    ligne = fields.Char(string='Ligne de production', help='Ex. Ligne 1')
    site_id = fields.Many2one('ka.site', string='Site')
    workcenter_id = fields.Many2one('mrp.workcenter', string='Poste de charge')
    immo_id = fields.Many2one('ka.immo', string='Immobilisation')
    marque = fields.Char(string='Marque')
    modele = fields.Char(string='Modèle')
    marque_modele = fields.Char(compute='_compute_txt', string='Marque / modèle')
    numero_serie = fields.Char(string='Numéro de série constructeur')
    puissance = fields.Char(string='Puissance')
    capacite = fields.Char(string='Capacité')
    mise_en_service = fields.Date(string='Mise en service')
    mise_en_service_txt = fields.Char(compute='_compute_txt', string='Mise en service')
    image = fields.Image(string='Photo', max_width=1024, max_height=1024)
    fournisseur_id = fields.Many2one('res.partner', string='Fournisseur')
    garantie_fin = fields.Date(string='Fin de garantie')
    compteur_heures = fields.Float(string='Compteur heures', digits=(12, 0))
    compteur_tonnage = fields.Float(string='Tonnage traité (t)', digits=(12, 1))
    compteur_cycles = fields.Float(string='Cycles', digits=(12, 0))
    heures_txt = fields.Char(compute='_compute_txt', string='Heures marche')
    criticite = fields.Selection(CRITICITE, string='Criticité', default='important', required=True, tracking=True)
    criticite_txt = fields.Char(compute='_compute_txt', string='Criticité')
    analytic_id = fields.Many2one('account.analytic.account', string='Compte analytique équipement')
    equipe_id = fields.Many2one('ka.mnt.equipe', string='Équipe de maintenance')
    plan_ids = fields.One2many('ka.mnt.plan', 'equipement_id', string='Plans préventifs')
    ot_ids = fields.One2many('ka.mnt.ot', 'equipement_id', string='Historique des interventions')
    releve_ids = fields.One2many('ka.mnt.releve', 'equipement_id', string='Relevés de compteur')
    contrat_ids = fields.Many2many('ka.mnt.contrat', string='Contrats de maintenance')
    nb_ot = fields.Integer(compute='_compute_fiabilite', string='Interventions')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    # indicateurs de fiabilité (§ 10.7) sur douze mois glissants
    mtbf = fields.Float(compute='_compute_fiabilite', string='MTBF (h)', digits=(10, 0))
    mttr = fields.Float(compute='_compute_fiabilite', string='MTTR (h)', digits=(10, 2))
    disponibilite = fields.Float(compute='_compute_fiabilite', string='Disponibilité (%)', digits=(5, 1))
    ratio_preventif = fields.Float(compute='_compute_fiabilite', string='Préventif / total (%)', digits=(5, 1))
    cout_maintenance = fields.Monetary(compute='_compute_fiabilite', string='Coût de maintenance (12 mois)')
    prochaine_panne = fields.Date(compute='_compute_fiabilite', string='Prochaine panne prévisionnelle')
    state = fields.Selection([('service', 'En service'), ('arret', "À l'arrêt"), ('reforme', 'Réformé')],
                             default='service', string='Statut', tracking=True)

    @api.depends('code', 'parent_id.complete_code')
    def _compute_complete(self):
        for e in self:
            e.complete_code = '%s/%s' % (e.parent_id.complete_code, e.code) if e.parent_id else (e.code or '')

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for e in self:
            e.display_name = '%s — %s' % (e.code, e.name) if e.code else (e.name or '')

    def _ka_subtitle(self):
        self.ensure_one()
        return ' · '.join(x for x in (self.code, _('Atelier %s') % self.atelier.lower() if self.atelier else '', self.ligne) if x)

    @api.depends('marque', 'modele', 'mise_en_service', 'compteur_heures', 'criticite')
    def _compute_txt(self):
        crit = dict(CRITICITE)
        for e in self:
            e.marque_modele = ' · '.join(x for x in (e.marque, e.modele) if x)
            e.mise_en_service_txt = e.mise_en_service.strftime('%m/%Y') if e.mise_en_service else ''
            e.heures_txt = nb(e.compteur_heures, 'h')
            e.criticite_txt = crit.get(e.criticite, '')

    @api.constrains('parent_id')
    def _check_parent(self):
        if self._has_cycle():
            raise ValidationError(_("Un équipement ne peut pas être rattaché à l'un de ses sous-ensembles."))

    @api.constrains('code')
    def _check_code(self):
        for e in self:
            if self.search_count([('code', '=', e.code)]) > 1:
                raise ValidationError(_('Le code équipement %s existe déjà.') % e.code)

    def _compute_fiabilite(self):
        """MTBF : temps de marche moyen entre deux pannes ; MTTR : durée moyenne d'arrêt corrective ; disponibilité :
        (temps requis − arrêts) / temps requis ; ratio préventif / correctif ; coût cumulé des OT clôturés."""
        today = fields.Date.context_today(self)
        debut = today - timedelta(days=365)
        for e in self:
            ots = e.ot_ids.filtered(lambda o: o.state == 'cloture' and o.date_cloture and o.date_cloture >= debut)
            pannes = ots.filtered(lambda o: o.type == 'correctif')
            requis = 365 * HEURES_REQUISES_JOUR
            arrets = sum(ots.mapped('duree_arret'))
            arrets_pannes = sum(pannes.mapped('duree_arret'))
            e.nb_ot = len(e.ot_ids)
            e.mttr = arrets_pannes / len(pannes) if pannes else 0.0
            e.mtbf = (requis - arrets_pannes) / len(pannes) if pannes else 0.0
            e.disponibilite = 100.0 * (requis - arrets) / requis if requis else 0.0
            e.ratio_preventif = 100.0 * len(ots.filtered(lambda o: o.type != 'correctif')) / len(ots) if ots else 0.0
            e.cout_maintenance = sum(ots.mapped('cout_total'))
            derniere = max(pannes.mapped('date_cloture')) if pannes else False
            e.prochaine_panne = derniere + timedelta(days=e.mtbf / HEURES_REQUISES_JOUR) if derniere and e.mtbf else False

    def action_creer_ot(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.mnt.ot', 'view_mode': 'form',
                'context': {'default_equipement_id': self.id, 'default_type': 'correctif'}}

    def action_open_ots(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Carnet de santé — %s') % self.name, 'res_model': 'ka.mnt.ot',
                'view_mode': 'list,form', 'domain': [('equipement_id', 'child_of', self.id)],
                'context': {'default_equipement_id': self.id}}

    def action_open_immo(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.immo', 'res_id': self.immo_id.id, 'view_mode': 'form'}

    def action_releve(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Relevé de compteur'), 'res_model': 'ka.mnt.releve',
                'view_mode': 'form', 'target': 'new', 'context': {'default_equipement_id': self.id}}

    def action_arreter(self):
        self.write({'state': 'arret'})

    def action_remettre_en_service(self):
        self.filtered(lambda e: e.state == 'arret').write({'state': 'service'})

    def action_reformer(self):
        self.write({'state': 'reforme'})


class KaMntReleve(models.Model):
    """Relevé de compteur (heures de marche, tonnage, cycles) : alimente les plans préventifs conditionnels (RG-10.1)."""
    _name = 'ka.mnt.releve'
    _description = 'Relevé de compteur'
    _order = 'date desc, id desc'

    equipement_id = fields.Many2one('ka.mnt.equipement', string='Équipement', required=True, ondelete='cascade')
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    type = fields.Selection([('heures', 'Heures de marche'), ('tonnage', 'Tonnage traité'), ('cycles', 'Cycles')],
                            string='Compteur', required=True, default='heures')
    valeur = fields.Float(string='Valeur relevée', required=True, digits=(12, 1))
    origine = fields.Char(string='Origine', default='Saisie')

    _CHAMP = {'heures': 'compteur_heures', 'tonnage': 'compteur_tonnage', 'cycles': 'compteur_cycles'}

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        for r in recs:
            champ = self._CHAMP[r.type]
            if r.valeur < r.equipement_id[champ]:
                raise ValidationError(_('Le relevé (%s) est inférieur au compteur actuel (%s).') % (r.valeur, r.equipement_id[champ]))
            r.equipement_id[champ] = r.valeur
        recs.equipement_id.plan_ids.filtered(lambda p: p.state == 'actif').verifier_echeances()
        return recs
