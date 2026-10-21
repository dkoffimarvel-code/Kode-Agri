from datetime import datetime, timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import heures

JOURS = ('Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche')
MODES = [('badge', 'Badge'), ('pin', 'Code PIN'), ('biometrie', 'Biométrie'), ('kiosque', 'Borne (kiosque)'),
         ('manuel', 'Manuel'), ('api', 'Import API')]


class KaRhFeuille(models.Model):
    """Feuille de pointage hebdomadaire : pointages consolidés, rapprochés de l'horaire théorique, régularisés puis
    transmis à la paie (§ 7.2.1). Une feuille comportant une anomalie non arbitrée n'est pas transmise (RG-7.1)."""
    _name = 'ka.rh.feuille'
    _description = 'Feuille de pointage'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'date_debut desc, employe_id'

    employe_id = fields.Many2one('ka.rh.employe', string='Employé', required=True)
    affectation_id = fields.Many2one(related='employe_id.affectation_id', store=True, string='Affectation')
    date_debut = fields.Date(string='Semaine du', required=True)
    date_fin = fields.Date(compute='_compute_fin', store=True, string='au')
    ligne_ids = fields.One2many('ka.rh.pointage', 'feuille_id', string='Pointages')
    ecart_ids = fields.One2many('ka.rh.pointage', 'feuille_id', string='Écarts', domain=[('anomalie', '!=', 'aucune')])
    heures_theoriques = fields.Float(compute='_compute_totaux', string='Heures théoriques', store=True)
    heures_pointees = fields.Float(compute='_compute_totaux', string='Heures pointées', store=True)
    heures_sup = fields.Float(compute='_compute_totaux', string='Heures supplémentaires', store=True)
    nb_anomalies = fields.Integer(compute='_compute_totaux', string='Anomalies en attente', store=True)
    theoriques_txt = fields.Char(compute='_compute_txt', string='Heures théoriques')
    pointees_txt = fields.Char(compute='_compute_txt', string='Heures pointées')
    sup_txt = fields.Char(compute='_compute_txt', string='Heures supplémentaires')
    statut_txt = fields.Char(compute='_compute_txt', string='Statut de la feuille')
    anomalie_html = fields.Html(compute='_compute_txt', sanitize=False)
    titre = fields.Char(compute='_compute_txt')
    anomalie_titre = fields.Char(compute='_compute_txt')
    event_ids = fields.One2many('ka.rh.pointage.event', 'feuille_id', string='Événements de pointeuse')
    state = fields.Selection([('brut', 'Brut'), ('controlee', 'Contrôlée'), ('validee', 'Validée'),
                              ('transmise', 'Transmise à la paie')], default='brut', string='Statut', tracking=True)

    @api.depends('date_debut')
    def _compute_fin(self):
        for f in self:
            f.date_fin = f.date_debut + timedelta(days=6) if f.date_debut else False

    @api.depends('employe_id', 'date_debut', 'date_fin')
    def _compute_display_name(self):
        for f in self:
            if f.date_debut and f.date_fin:
                f.display_name = '%s — Semaine du %s-%s' % (f.employe_id.matricule or '', f.date_debut.strftime('%d'),
                                                           f.date_fin.strftime('%d/%m/%Y'))
            else:
                f.display_name = f.employe_id.matricule or _('Nouvelle feuille')

    def _ka_subtitle(self):
        self.ensure_one()
        e = self.employe_id
        return ' · '.join(x for x in (e.matricule, e.poste, e.affectation_id.name) if x)

    @api.depends('ligne_ids.heures', 'ligne_ids.heures_sup', 'ligne_ids.anomalie', 'ligne_ids.resolue',
                 'employe_id.horaire_hebdo')
    def _compute_totaux(self):
        for f in self:
            f.heures_theoriques = f.employe_id.horaire_hebdo or 40.0
            f.heures_pointees = sum(f.ligne_ids.mapped('heures'))
            f.heures_sup = sum(f.ligne_ids.mapped('heures_sup'))
            f.nb_anomalies = len(f.ligne_ids.filtered(lambda l: l.anomalie != 'aucune' and not l.resolue))

    def _compute_txt(self):
        etats = dict(self._fields['state'].selection)
        for f in self:
            f.theoriques_txt, f.pointees_txt, f.sup_txt = (heures(f.heures_theoriques), heures(f.heures_pointees),
                                                           heures(f.heures_sup))
            n = f.nb_anomalies
            f.statut_txt = etats[f.state] + ((' — %d anomalie%s en attente' % (n, 's' if n > 1 else '')) if n else '')
            f.titre = _('Feuille de pointage — Semaine du %s au %s') % (
                f.date_debut.strftime('%d') if f.date_debut else '', f.date_fin.strftime('%d/%m/%Y') if f.date_fin else '')
            att = f.ligne_ids.filtered(lambda l: l.anomalie != 'aucune' and not l.resolue)
            f.anomalie_titre = _('%d anomalie%s à régulariser') % (len(att), 's' if len(att) > 1 else '')
            f.anomalie_html = ''.join(
                '<div>%s %s — %s Cette feuille ne peut pas être transmise à la paie tant que l\'anomalie n\'est pas '
                'arbitrée (RG-7.1).</div>' % (JOURS[l.date.weekday()], l.date.strftime('%d/%m'), l.anomalie_detail)
                for l in att) if att else False

    # ---- cycle --------------------------------------------------------------------------------------------------
    def action_importer(self):
        """Importe les pointages reçus de la pointeuse (API) pour la semaine, puis contrôle la feuille (§ 7.2.2)."""
        for f in self:
            if f.state not in ('brut', 'controlee'):
                raise UserError(_('La feuille est déjà validée.'))
            debut = datetime.combine(f.date_debut, datetime.min.time())
            evts = self.env['ka.rh.pointage.event'].search([
                ('employe_id', '=', f.employe_id.id), ('statut', '=', 'rapproche'),
                ('horodatage', '>=', debut), ('horodatage', '<', debut + timedelta(days=7))], order='horodatage')
            for jour in sorted(set(fields.Datetime.context_timestamp(f, e.horodatage).date() for e in evts)):
                du_jour = evts.filtered(lambda e: fields.Datetime.context_timestamp(f, e.horodatage).date() == jour)
                ent = du_jour.filtered(lambda e: e.sens == 'entree')[:1]
                sor = du_jour.filtered(lambda e: e.sens == 'sortie')[-1:]
                h = lambda e: (fields.Datetime.context_timestamp(f, e.horodatage).hour
                               + fields.Datetime.context_timestamp(f, e.horodatage).minute / 60.0) if e else 0.0
                vals = {'date': jour, 'entree': h(ent), 'sortie': h(sor), 'mode': ent.mode or sor.mode or 'api'}
                ligne = f.ligne_ids.filtered(lambda l: l.date == jour)
                ligne.write(vals) if ligne else f.write({'ligne_ids': [Command.create(vals)]})
                du_jour.write({'feuille_id': f.id})
            f.action_controler()

    def action_controler(self):
        """Rapproche les pointages de l'horaire théorique : jour ouvré sans pointage, sortie manquante ou incohérente."""
        for f in self:
            for i in range(5):   # jours ouvrés du lundi au vendredi
                jour = f.date_debut + timedelta(days=i)
                if not f.ligne_ids.filtered(lambda l: l.date == jour) and \
                        not self.env['ka.rh.demande'].couvre(f.employe_id, jour):
                    f.write({'ligne_ids': [Command.create({'date': jour})]})
            for l in f.ligne_ids:
                l.anomalie = l._detecter()
            f.state = 'controlee'

    def action_regulariser(self):
        """Arbitrage du responsable : une anomalie est levée par une saisie corrigée (entrée et sortie) ou un motif."""
        for f in self:
            for l in f.ligne_ids.filtered(lambda x: x.anomalie != 'aucune' and not x.resolue):
                if l.motif_regul or (l.entree and l.sortie and l.sortie > l.entree):
                    if l.entree and l.sortie and l.sortie > l.entree:
                        l.write({'mode': 'manuel', 'anomalie': 'aucune'})
                    l.resolue = True
            if f.nb_anomalies:
                return self.env['ka.rh.employe']._notif(
                    _('Régularisation'), _("Saisissez l'entrée et la sortie, ou un motif, sur chaque ligne en anomalie."), 'warning')

    def action_valider(self):
        for f in self:
            if f.state == 'brut':
                f.action_controler()
            if f.nb_anomalies:
                raise UserError(_('%s anomalie(s) non arbitrée(s) : la feuille ne peut être validée ni transmise à la '
                                  'paie (RG-7.1).') % f.nb_anomalies)
            f.state = 'validee'

    def action_transmettre(self):
        for f in self:
            if f.state != 'validee':
                raise UserError(_('Seule une feuille validée est transmise à la paie.'))
            f.state = 'transmise'


class KaRhPointage(models.Model):
    """Pointage d'une journée : entrée, sortie, mode de saisie et écart à l'horaire théorique."""
    _name = 'ka.rh.pointage'
    _description = 'Pointage journalier'
    _order = 'date'

    feuille_id = fields.Many2one('ka.rh.feuille', required=True, ondelete='cascade')
    date = fields.Date(string='Date', required=True)
    jour = fields.Char(compute='_compute_jour', string='Jour')
    entree = fields.Float(string='Entrée')
    sortie = fields.Float(string='Sortie')
    mode = fields.Selection(MODES, string='Mode de saisie')
    heures = fields.Float(compute='_compute_heures', string='Heures', store=True)
    heures_sup = fields.Float(compute='_compute_heures', string='Heures sup.', store=True)
    heures_txt = fields.Char(compute='_compute_heures', string='Heures')
    anomalie = fields.Selection([('aucune', 'Aucune'), ('manquant', 'Pointage manquant'), ('doublon', 'Doublon'),
                                 ('incomplet', 'Pointage incomplet'), ('incoherent', 'Horodatage incohérent')],
                                string='Anomalie', default='aucune')
    anomalie_detail = fields.Char(compute='_compute_ecart')
    resolue = fields.Boolean(string='Arbitrée')
    motif_regul = fields.Char(string='Motif de régularisation')
    ecart = fields.Char(compute='_compute_ecart', string='Écart')

    @api.depends('date')
    def _compute_jour(self):
        for l in self:
            l.jour = '%s %s' % (JOURS[l.date.weekday()], l.date.strftime('%d/%m')) if l.date else ''

    @api.depends('entree', 'sortie', 'feuille_id.employe_id.horaire_hebdo')
    def _compute_heures(self):
        for l in self:
            h = (l.sortie - l.entree) if l.entree and l.sortie and l.sortie > l.entree else 0.0
            journalier = (l.feuille_id.employe_id.horaire_hebdo or 40.0) / 5
            l.heures = h
            l.heures_sup = max(h - journalier, 0.0) if l.date and l.date.weekday() < 5 else h
            l.heures_txt = heures(h)

    @api.depends('anomalie', 'resolue', 'heures_sup', 'entree', 'sortie', 'heures')
    def _compute_ecart(self):
        details = {'manquant': _('aucun pointage reçu (ni saisie directe, ni import API).'),
                   'incomplet': _('entrée ou sortie manquante.'), 'doublon': _('pointage reçu en double.'),
                   'incoherent': _('horodatage incohérent avec l\'horaire théorique.')}
        for l in self:
            l.anomalie_detail = details.get(l.anomalie, '')
            if l.anomalie != 'aucune' and not l.resolue:
                l.ecart = _('Anomalie : %s') % dict(self._fields['anomalie'].selection)[l.anomalie].lower()
            elif l.heures_sup > 0:
                l.ecart = _('+%s (heures sup.)') % heures(l.heures_sup)
            elif l.resolue and l.motif_regul:
                l.ecart = _('Régularisé : %s') % l.motif_regul
            else:
                l.ecart = '—'

    def _detecter(self):
        self.ensure_one()
        if self.resolue:
            return self.anomalie
        if not self.entree and not self.sortie:
            return 'manquant'
        if not self.entree or not self.sortie:
            return 'incomplet'
        if self.sortie <= self.entree or self.sortie - self.entree > 16:
            return 'incoherent'
        return 'aucune'


class KaRhPointageEvent(models.Model):
    """Événement transmis par la pointeuse externe (badge, RFID, biométrie) via l'API d'Odoo (§ 7.2.2).

    Appel par l'API externe (JSON-RPC / XML-RPC), en temps réel ou par lot :
        models.execute_kw(db, uid, cle, 'ka.rh.pointage.event', 'recevoir',
                          [[{'identifiant': 'B-0211', 'horodatage': '2026-06-15 06:58:00', 'sens': 'entree',
                             'terminal': 'ATELIER-L2'}]])
    Les événements sont rapprochés de la fiche employé par le badge ou le matricule ; doublons et pointages incohérents
    sont mis en anomalie pour arbitrage (RG-7.1)."""
    _name = 'ka.rh.pointage.event'
    _description = 'Événement de pointeuse'
    _order = 'horodatage desc'

    identifiant = fields.Char(string='Identifiant du pointage', required=True, help='Badge, RFID ou identifiant biométrique')
    horodatage = fields.Datetime(string='Horodatage', required=True)
    sens = fields.Selection([('entree', 'Entrée'), ('sortie', 'Sortie')], string='Sens', required=True)
    terminal = fields.Char(string='Site ou terminal')
    mode = fields.Selection(MODES, string='Mode', default='badge')
    transmission = fields.Selection([('temps_reel', 'Temps réel'), ('lot', 'Synchronisation par lot')],
                                    string='Mode de transmission', default='temps_reel')
    employe_id = fields.Many2one('ka.rh.employe', string='Employé')
    feuille_id = fields.Many2one('ka.rh.feuille', string='Feuille de pointage')
    statut = fields.Selection([('recu', 'Reçu'), ('rapproche', 'Rapproché à un employé'), ('anomalie', 'En anomalie'),
                               ('rejete', 'Rejeté')], string='Statut de synchronisation', default='recu')
    motif = fields.Char(string='Motif')

    @api.model
    def recevoir(self, evenements):
        """Point d'entrée de l'API : crée les événements puis les rapproche. Retourne le nombre par statut."""
        crees = self.create([{
            'identifiant': e['identifiant'], 'horodatage': e['horodatage'], 'sens': e['sens'],
            'terminal': e.get('terminal'), 'mode': e.get('mode', 'badge'),
            'transmission': e.get('transmission', 'temps_reel' if len(evenements) == 1 else 'lot')} for e in evenements])
        crees.rapprocher()
        return {s: len(crees.filtered(lambda x: x.statut == s)) for s in ('rapproche', 'anomalie', 'rejete')}

    def rapprocher(self):
        Emp = self.env['ka.rh.employe']
        for e in self.filtered(lambda x: x.statut in ('recu', 'anomalie')):
            emp = Emp.search(['|', ('badge', '=', e.identifiant), ('matricule', '=', e.identifiant)], limit=1)
            if not emp:
                e.write({'statut': 'rejete', 'motif': _('Identifiant inconnu')})
                continue
            doublon = self.search_count([('id', '!=', e.id), ('employe_id', '=', emp.id), ('sens', '=', e.sens),
                                         ('statut', '=', 'rapproche'),
                                         ('horodatage', '>=', e.horodatage - timedelta(minutes=2)),
                                         ('horodatage', '<=', e.horodatage + timedelta(minutes=2))])
            if doublon:
                e.write({'employe_id': emp.id, 'statut': 'anomalie', 'motif': _('Doublon')})
            elif emp.state != 'actif':
                e.write({'employe_id': emp.id, 'statut': 'anomalie', 'motif': _('Employé non actif')})
            else:
                e.write({'employe_id': emp.id, 'statut': 'rapproche', 'motif': False})

    @api.model
    def _cron_rapprocher(self):
        self.search([('statut', '=', 'recu')]).rapprocher()
