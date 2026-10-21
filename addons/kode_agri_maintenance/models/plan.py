from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .equipement import nb

DECLENCHEURS = [('heures', 'Compteur (heures)'), ('tonnage', 'Compteur (tonnage)'), ('cycles', 'Compteur (cycles)'),
                ('calendrier', 'Calendaire'), ('legal', 'Échéance légale')]
COMPTEUR = {'heures': 'compteur_heures', 'tonnage': 'compteur_tonnage', 'cycles': 'compteur_cycles'}
UNITE = {'heures': 'h', 'tonnage': 't', 'cycles': 'cycles'}


class KaMntPlan(models.Model):
    """Plan de maintenance préventive (§ 10.3) : opérations récurrentes, périodicité calendaire ou sur compteur, gamme et
    pièces. À l'approche de l'échéance, l'OT préventif est généré avec sa gamme et sa liste de pièces (RG-10.1)."""
    _name = 'ka.mnt.plan'
    _description = 'Plan de maintenance préventive'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'equipement_id, name'

    name = fields.Char(string='Référence', readonly=True, copy=False, default='Nouveau')
    intitule = fields.Char(string='Intitulé', required=True, help='Ex. Graissage paliers')
    equipement_id = fields.Many2one('ka.mnt.equipement', string='Équipement', required=True, ondelete='cascade')
    type = fields.Selection([('preventif', 'Préventive systématique'), ('conditionnel', 'Préventive conditionnelle'),
                             ('reglementaire', 'Réglementaire')], compute='_compute_type', store=True, string='Type')
    declencheur = fields.Selection(DECLENCHEURS, string='Type de déclencheur', required=True, default='heures')
    periodicite = fields.Float(string='Périodicité (compteur)', digits=(12, 0), help='Ex. 500 (heures)')
    intervalle = fields.Integer(string='Intervalle calendaire', default=3)
    unite = fields.Selection([('jours', 'Jours'), ('semaines', 'Semaines'), ('mois', 'Mois'), ('ans', 'Ans')],
                             string='Unité', default='mois')
    periodicite_txt = fields.Char(compute='_compute_echeance', string='Périodicité')
    periodicite_kpi = fields.Char(compute='_compute_echeance', string='Périodicité')
    anticipation = fields.Float(string='Anticipation', digits=(10, 0), default=50,
                                help="Avance de génération de l'OT : en unités de compteur, ou en jours pour un plan calendaire")
    derniere_valeur = fields.Float(string='Dernière exécution (compteur)', digits=(12, 0))
    derniere_date = fields.Date(string='Dernière exécution (date)')
    prochaine_valeur = fields.Float(compute='_compute_echeance', string='Prochaine échéance (compteur)', store=True, digits=(12, 0))
    prochaine_date = fields.Date(compute='_compute_echeance', string='Prochaine échéance (date)', store=True)
    derniere_txt = fields.Char(compute='_compute_echeance', string='Dernière exécution')
    prochaine_txt = fields.Char(compute='_compute_echeance', string='Prochaine échéance')
    proche = fields.Boolean(compute='_compute_echeance', string='Échéance proche')
    duree_estimee = fields.Float(string='Durée estimée (h)', digits=(6, 1))
    generation = fields.Selection([('auto', 'Auto'), ('manuelle', 'Manuelle')], string='Génération OT', default='auto')
    externe = fields.Boolean(string='Réalisé par un prestataire')
    contrat_id = fields.Many2one('ka.mnt.contrat', string='Contrat de maintenance')
    operation_ids = fields.One2many('ka.mnt.plan.operation', 'plan_id', string='Gamme et pièces du plan')
    ot_ids = fields.One2many('ka.mnt.ot', 'plan_id', string='OT générés')
    titre = fields.Char(compute='_compute_echeance')
    state = fields.Selection([('brouillon', 'Brouillon'), ('actif', 'Actif')], default='brouillon', string='Statut',
                             tracking=True)

    @api.depends('name', 'intitule')
    def _compute_display_name(self):
        for p in self:
            p.display_name = p.name if p.name and p.name != 'Nouveau' else (p.intitule or _('Nouveau plan'))

    def _ka_subtitle(self):
        self.ensure_one()
        mode = _('déclenchement sur compteur') if self.declencheur in COMPTEUR else (
            _('déclenchement calendaire') if self.declencheur == 'calendrier' else _('échéance légale'))
        return '%s · %s' % (self.equipement_id.code or '', mode)

    @api.depends('declencheur')
    def _compute_type(self):
        for p in self:
            p.type = 'conditionnel' if p.declencheur in COMPTEUR else ('reglementaire' if p.declencheur == 'legal' else 'preventif')

    def _delta(self):
        return {'jours': relativedelta(days=self.intervalle), 'semaines': relativedelta(weeks=self.intervalle),
                'mois': relativedelta(months=self.intervalle), 'ans': relativedelta(years=self.intervalle)}[self.unite or 'mois']

    @api.depends('declencheur', 'periodicite', 'intervalle', 'unite', 'derniere_valeur', 'derniere_date', 'intitule',
                 'anticipation', 'equipement_id.compteur_heures', 'equipement_id.compteur_tonnage', 'equipement_id.compteur_cycles')
    def _compute_echeance(self):
        today = fields.Date.context_today(self)
        libelles = {'jours': 'jours', 'semaines': 'semaines', 'mois': 'mois', 'ans': 'ans'}
        for p in self:
            p.titre = _('Plan préventif — %s') % (p.intitule or '')
            if p.declencheur in COMPTEUR:
                u = UNITE[p.declencheur]
                p.prochaine_valeur = p.derniere_valeur + p.periodicite
                p.prochaine_date = False
                actuel = p.equipement_id[COMPTEUR[p.declencheur]]
                p.proche = bool(p.periodicite) and actuel >= p.prochaine_valeur - p.anticipation
                p.periodicite_kpi = nb(p.periodicite, u)
                p.periodicite_txt = _('Toutes les %s') % nb(p.periodicite, u)
                p.derniere_txt = nb(p.derniere_valeur, u)
                p.prochaine_txt = nb(p.prochaine_valeur, u) + (_(' (proche)') if p.proche else '')
            else:
                base = p.derniere_date or today
                p.prochaine_valeur = 0.0
                p.prochaine_date = base + p._delta() if p.intervalle else False
                p.proche = bool(p.prochaine_date) and p.prochaine_date <= today + relativedelta(days=int(p.anticipation or 0))
                txt = {('mois', 3): 'Trimestrielle', ('mois', 6): 'Semestrielle', ('ans', 1): 'Annuelle',
                       ('mois', 1): 'Mensuelle', ('mois', 12): 'Annuelle'}.get((p.unite, p.intervalle))
                p.periodicite_kpi = '%s %s' % (p.intervalle, libelles.get(p.unite, ''))
                p.periodicite_txt = txt or _('Tous les %s %s') % (p.intervalle, libelles.get(p.unite, ''))
                p.derniere_txt = p.derniere_date.strftime('%d/%m/%Y') if p.derniere_date else _('—')
                p.prochaine_txt = (p.prochaine_date.strftime('%d/%m/%Y') if p.prochaine_date else '') + (_(' (proche)') if p.proche else '')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.mnt.plan')
        return super().create(vals_list)

    def action_activer(self):
        for p in self:
            if p.declencheur in COMPTEUR and not p.periodicite:
                raise UserError(_('Renseignez la périodicité du compteur.'))
            if p.declencheur in COMPTEUR and not p.derniere_valeur:
                p.derniere_valeur = p.equipement_id[COMPTEUR[p.declencheur]]
            if p.declencheur not in COMPTEUR and not p.derniere_date:
                p.derniere_date = fields.Date.context_today(self)
            p.state = 'actif'

    def action_generer_ot(self):
        """Génère l'OT à échéance (bouton « Générer OT à échéance ») même si le seuil d'anticipation n'est pas atteint."""
        ots = self.env['ka.mnt.ot']
        for p in self:
            ots |= p._generer_ot()
        if len(ots) == 1:
            return {'type': 'ir.actions.act_window', 'res_model': 'ka.mnt.ot', 'res_id': ots.id, 'view_mode': 'form'}

    def _generer_ot(self):
        self.ensure_one()
        ouvert = self.ot_ids.filtered(lambda o: o.state not in ('cloture', 'annule'))
        if ouvert:
            return ouvert[:1]
        e = self.equipement_id
        echeance = self.prochaine_txt.replace(_(' (proche)'), '')
        ot = self.env['ka.mnt.ot'].create({
            'equipement_id': e.id, 'plan_id': self.id, 'type': 'preventif',
            'priorite': 'haute' if e.criticite == 'critique' else 'normale', 'objet': '%s — échéance %s' % (self.intitule, echeance),
            'duree_estimee': self.duree_estimee, 'externe': self.externe, 'contrat_id': self.contrat_id.id,
            'technicien_id': e.equipe_id.technicien_ids[:1].id,
            'ligne_ids': [Command.create({'type': 'piece', 'detail': '%s — %s' % (o.name, o.product_id.name or ''),
                                          'product_id': o.product_id.id, 'quantite': o.quantite})
                          for o in self.operation_ids if o.product_id]
                         + [Command.create({'type': 'operation', 'detail': o.name}) for o in self.operation_ids if not o.product_id]})
        self.message_post(body=_('OT %s généré à l\'échéance %s (RG-10.1).') % (ot.name, echeance))
        return ot

    def verifier_echeances(self):
        """RG-10.1 : génération automatique des OT préventifs à l'approche de l'échéance (date ou seuil de compteur)."""
        for p in self.filtered(lambda x: x.state == 'actif' and x.generation == 'auto' and x.proche):
            p._generer_ot()

    @api.model
    def _cron_echeances(self):
        self.search([('state', '=', 'actif'), ('generation', '=', 'auto')]).verifier_echeances()

    def executer(self, ot):
        """Mise à jour de la dernière exécution à la clôture de l'OT."""
        for p in self:
            if p.declencheur in COMPTEUR:
                p.derniere_valeur = ot.compteur_cloture or p.equipement_id[COMPTEUR[p.declencheur]]
            p.derniere_date = ot.date_cloture or fields.Date.context_today(self)


class KaMntPlanOperation(models.Model):
    _name = 'ka.mnt.plan.operation'
    _description = 'Opération de gamme préventive'
    _order = 'sequence, id'

    plan_id = fields.Many2one('ka.mnt.plan', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Opération', required=True)
    product_id = fields.Many2one('product.product', string='Pièce / consommable', domain=[('ka_piece_mnt', '=', True)])
    quantite = fields.Float(string='Quantité', digits=(10, 2))
    uom_id = fields.Many2one(related='product_id.uom_id', string='Unité')
    quantite_txt = fields.Char(compute='_compute_qte', string='Quantité')

    @api.depends('quantite', 'uom_id')
    def _compute_qte(self):
        for o in self:
            o.quantite_txt = ('%g %s' % (o.quantite, o.uom_id.name or '')).replace('.', ',').strip() if o.product_id else '—'
