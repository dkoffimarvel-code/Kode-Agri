import base64
from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, models

PDF = base64.b64encode(b'%PDF-1.4\n% justificatif de demonstration\n%%EOF\n')

# matricule, nom, poste, affectation (xmlid), catégorie, ancienneté (mois), éléments (rubrique, type, montant), badge
PERSONNEL = [
    ('EMP-0211', 'Kouamé Yao', 'Opérateur séchage', 'aff_2', 'cat_1', 27,
     [('BASE', 'fixe_mensuel', 185_000), ('PRIM_POSTE', 'variable', 25_000), ('IND_TRANSPORT', 'fixe', 15_000)], 'B-0211'),
    ('EMP-0198', 'Konan Serge', 'Opérateur séchage', 'aff_2', 'cat_1', 40, [('BASE', 'fixe_mensuel', 175_000)], 'B-0198'),
    ('EMP-0223', 'Bamba Karim', 'Agent de maintenance', 'aff_1', 'cat_2', 30, [('BASE', 'fixe_mensuel', 260_000)], 'B-0223'),
    ('EMP-0230', 'Adjoua Kouassi', 'Technicienne de maintenance', 'aff_1', 'cat_2', 50, [('BASE', 'fixe_mensuel', 320_000)], 'B-0230'),
    ('EMP-0150', 'Traoré Issa', 'Chauffeur poids lourd', 'aff_3', 'cat_1', 70, [('BASE', 'fixe_mensuel', 210_000)], 'B-0150'),
    ('EMP-0151', 'Koffi Aya', 'Chauffeur', 'aff_3', 'cat_1', 20, [('BASE', 'fixe_mensuel', 190_000)], 'B-0151'),
    ('EMP-0142', 'Agent collecte', 'Agent collecte', 'aff_3', 'cat_1', 36, [('BASE', 'fixe_mensuel', 200_000)], 'B-0142'),
]


class KaDemoRh(models.AbstractModel):
    _inherit = 'ka.demo'

    def _employe(self, matricule):
        return self.env['ka.rh.employe'].search([('matricule', '=', matricule)], limit=1)

    def _m7_rh(self):
        if self._employe('EMP-0211'):
            return 'déjà chargé'
        today = date.today()
        rub = lambda code: self.env['ka.rh.rubrique'].par_code(code)
        usinage = self._analytique('USINAGE')
        for mat, nom, poste, aff, cat, anc, elements, badge in PERSONNEL:
            e = self.env['ka.rh.employe'].create({
                'matricule': mat, 'name': nom, 'poste': poste, 'affectation_id': self._ref('kode_agri_rh.%s' % aff).id,
                'categorie_id': self._ref('kode_agri_rh.%s' % cat).id, 'date_entree': today - relativedelta(months=anc),
                'analytic_id': usinage.id if aff in ('aff_1', 'aff_2') and usinage else False, 'badge': badge,
                'situation': 'marie' if anc > 30 else 'celibataire', 'nb_enfants': 2 if anc > 30 else 0,
                'element_ids': [Command.create({'rubrique_id': rub(r).id, 'type': t, 'montant': m}) for r, t, m in elements]})
            e.action_activer()
        op = self._employe('EMP-0211')
        comp = lambda i: self._ref('kode_agri_rh.comp_%d' % i)
        op.competence_ids = [Command.create({'competence_id': comp(1).id, 'niveau': 'confirme', 'origine': 'Embauche'}),
                             Command.create({'competence_id': comp(3).id, 'niveau': 'debutant', 'origine': 'Embauche'})]
        # soldes de congés de l'écran 7.2.4 : 26,4 jours acquis, 11,9 pris ; récupération 3 / 1
        for s in op.solde_ids:
            s.write({'acquis': 26.4, 'pris': 11.9} if s.type_id.code == 'CA' else {'acquis': 3.0, 'pris': 1.0})
        res = [self._m7_pointage(op), self._m7_conges(op), self._m7_paie(op), self._m7_missions(), self._m7_recrutement(),
               self._m7_formation(op)]
        return '%d salariés ; %s' % (len(PERSONNEL), ' ; '.join(res))

    def _m7_pointage(self, op):
        """Semaine précédente : pointages reçus par l'API de la pointeuse, jeudi sans pointage (anomalie RG-7.1).
        Semaine d'avant : feuille validée et transmise à la paie, avec heures supplémentaires."""
        Evt = self.env['ka.rh.pointage.event']
        lundi = date.today() - timedelta(days=date.today().weekday() + 7)

        def evt(jour, h, m, sens):
            return {'identifiant': op.badge, 'horodatage': datetime.combine(jour, time(h, m)).strftime('%Y-%m-%d %H:%M:%S'),
                    'sens': sens, 'terminal': 'ATELIER-L2'}
        horaires = {0: ((6, 58), (15, 4)), 1: ((7, 2), (15, 0)), 2: ((6, 59), (17, 12)), 4: ((7, 0), (15, 1))}
        lot = []
        for j, (e_, s_) in horaires.items():
            lot += [evt(lundi + timedelta(days=j), *e_, 'entree'), evt(lundi + timedelta(days=j), *s_, 'sortie')]
        bilan = Evt.recevoir(lot)
        f = self.env['ka.rh.feuille'].create({'employe_id': op.id, 'date_debut': lundi})
        f.action_importer()
        f.ligne_ids.filtered(lambda l: l.date.weekday() == 2).write({'mode': 'api'})
        # semaine précédente : complète, régularisée, validée et transmise
        lundi2 = lundi - timedelta(days=7)
        lot = []
        for j in range(5):
            fin = (18, 0) if j in (1, 3) else (15, 0)
            lot += [evt(lundi2 + timedelta(days=j), 7, 0, 'entree'), evt(lundi2 + timedelta(days=j), *fin, 'sortie')]
        Evt.recevoir(lot)
        f2 = self.env['ka.rh.feuille'].create({'employe_id': op.id, 'date_debut': lundi2})
        f2.action_importer()
        f2.action_valider()
        f2.action_transmettre()
        return 'pointeuse : %d événements rapprochés, feuille en anomalie (RG-7.1) et feuille transmise à la paie' % bilan['rapproche']

    def _m7_conges(self, op):
        today = date.today()
        debut = today + timedelta(days=(7 - today.weekday()) % 7 + 14)   # un lundi dans trois semaines
        ca = self._ref('kode_agri_rh.tc_ca')
        cg = self.env['ka.rh.demande'].create({'type_demande': 'conge', 'employe_id': op.id, 'type_conge_id': ca.id,
                                               'date_debut': debut, 'date_fin': debut + timedelta(days=4)})
        cg.action_soumettre()
        ab = self.env['ka.rh.demande'].create({
            'type_demande': 'absence', 'employe_id': op.id, 'motif': 'maladie', 'date_debut': today - timedelta(days=12),
            'date_fin': today - timedelta(days=10), 'justificatif': PDF, 'justificatif_nom': 'certificat_medical.pdf', 'delai': '48h'})
        ab.action_soumettre()
        ab.action_approuver()   # responsable hiérarchique
        ab.action_approuver()   # service RH
        pm = self.env['ka.rh.demande'].create({
            'type_demande': 'permission', 'employe_id': self._employe('EMP-0198').id, 'evenement': 'naissance', 'foyer': True,
            'date_debut': today - timedelta(days=20), 'date_fin': today - timedelta(days=18)})
        pm.action_soumettre()
        return 'congé %s à approuver, absence maladie et permission' % cg.name

    def _m7_paie(self, op):
        mois = date.today().replace(day=1) - relativedelta(months=1)
        b = self.env['ka.rh.bulletin'].create({'employe_id': op.id, 'periode': mois})
        b.action_calculer()
        b.action_confirmer()
        lot = self.env['ka.rh.bulletin'].generer_lot(date.today().replace(day=1))
        nb = self.env['ka.rh.bulletin'].search_count(lot['domain'])
        return 'bulletin %s confirmé et comptabilisé (net %s FCFA), %d bulletins du mois calculés' % (b.name, round(b.net), nb)

    def _m7_missions(self):
        today = date.today()
        agent = self._employe('EMP-0142')
        zone = self._analytique('ACH_FDT')
        m = self.env['ka.rh.mission'].create({
            'employe_id': agent.id, 'objet': "Tournée d'achat FDT", 'titre_court': 'Tournée collecte Sud',
            'destination': 'Zone Sud (Daloa)', 'date_debut': today - timedelta(days=10), 'date_fin': today - timedelta(days=6),
            'avance_demandee': 175_000, 'analytic_id': zone.id if zone else False})
        m.action_soumettre()
        m.action_approuver()
        m.action_verser_avance()
        note = self.env['ka.frais.note'].search([('intitule', '=', 'Tournée collecte Sud')], limit=1)
        if note:
            m.note_ids = [Command.link(note.id)]
        m.action_decompter()
        m2 = self.env['ka.rh.mission'].create({
            'employe_id': agent.id, 'objet': "Tournée d'achat FDT", 'titre_court': 'Tournée collecte Sud',
            'destination': 'Zone Sud (Daloa)', 'date_debut': today + timedelta(days=3), 'date_fin': today + timedelta(days=7),
            'avance_demandee': 175_000, 'analytic_id': zone.id if zone else False})
        m2.action_soumettre()
        return 'missions %s (à régulariser) et %s (à approuver)' % (m.name, m2.name)

    def _m7_recrutement(self):
        aff = self._ref('kode_agri_rh.aff_2')
        dp = self.env['ka.rh.demande.personnel'].create({
            'poste': 'Opérateur séchage', 'affectation_id': aff.id, 'demandeur': "Chef d'atelier Ligne 2", 'motif': 'depart',
            'type_contrat': 'cdi', 'effectif': 1, 'date_souhaitee': date.today() + relativedelta(months=2, day=1),
            'categorie_id': self._ref('kode_agri_rh.cat_1').id, 'categorie_txt': 'Ouvrier — atelier production', 'budget': 185_000,
            'justification': "Départ à la retraite de l'opérateur titulaire. Le poste est identifié comme critique pour la "
                             "continuité de la ligne 2 (séchage) et ne peut rester vacant plus de quatre semaines."})
        dp.action_soumettre()
        dp.action_valider()   # hiérarchie
        dp.action_valider()   # RH
        dp.action_ouvrir_poste()
        cand = self.env['ka.rh.candidature'].create({
            'name': 'Awa Koffi', 'demande_id': dp.id, 'email': 'awa.koffi@email.ci', 'telephone': '07 XX XX XX XX',
            'source': 'spontanee', 'diplome': 'CAP Conduite de systèmes industriels', 'pretention': 180_000,
            'entretien_date': datetime.combine(date.today() + timedelta(days=3), time(10, 0)),
            'prochaine_etape': 'Test technique programmé. Un refus à ce stade doit être motivé (motif de refus tracé sur la candidature) '
                               'avant archivage.'})
        for ev, (note, com) in zip(cand.evaluation_ids, [('4', 'Bonne maîtrise du séchage industriel'),
                                                          ('5', 'Très bon relationnel, esprit d\'équipe'), ('5', 'Immédiate')]):
            ev.write({'note': note, 'commentaire': com})
        cand.action_preselectionner()
        cand.action_planifier_entretien()
        dp2 = self.env['ka.rh.demande.personnel'].create({
            'poste': 'Technicien électricien', 'affectation_id': self._ref('kode_agri_rh.aff_1').id, 'demandeur': 'Responsable maintenance',
            'motif': 'creation', 'effectif': 1, 'categorie_id': self._ref('kode_agri_rh.cat_2').id, 'budget': 350_000,
            'justification': 'Création de poste : maintenance électrique des nouvelles presses.'})
        dp2.action_soumettre()
        return 'demande %s approuvée, candidature %s en entretien, %s à valider' % (dp.name, cand.reference, dp2.name)

    def _m7_formation(self, op):
        today = date.today()
        hab = self._ref('kode_agri_rh.comp_2')
        s = self.env['ka.rh.session'].create({
            'intitule': 'Habilitation électrique BR', 'type': 'securite', 'organisme': 'CIDFOR', 'affectation_id': self._ref('kode_agri_rh.aff_2').id,
            'date_debut': today - timedelta(days=1), 'date_fin': today + timedelta(days=1), 'lieu': 'Centre CIDFOR, Yopougon',
            'cout': 450_000, 'fdfp': 'ta', 'places': 6, 'origine': 'Plan de formation %s — obligation sécurité' % today.year,
            'plan': 'Plan de formation %s' % today.year, 'competence_id': hab.id, 'niveau_vise': 'acquis',
            'participant_ids': [Command.create({'employe_id': op.id, 'jours_presents': 3, 'resultat': 'valide'}),
                                Command.create({'employe_id': self._employe('EMP-0198').id, 'jours_presents': 2, 'resultat': 'attente'}),
                                Command.create({'employe_id': self._employe('EMP-0223').id, 'jours_presents': 3, 'resultat': 'valide'})]})
        s.action_demarrer()
        ancien = self.env['ka.rh.session'].create({
            'intitule': 'Conduite de séchoir — perfectionnement', 'type': 'interne', 'organisme': 'Formation interne',
            'date_debut': today - relativedelta(months=3), 'date_fin': today - relativedelta(months=3) + timedelta(days=1), 'cout': 120_000,
            'competence_id': self._ref('kode_agri_rh.comp_1').id, 'niveau_vise': 'confirme',
            'participant_ids': [Command.create({'employe_id': self._employe('EMP-0198').id, 'jours_presents': 2, 'resultat': 'valide'})]})
        ancien.action_cloturer()   # RG-7.8 : compétence mise à jour sur la fiche du participant
        Ent = self.env['ka.rh.entretien']
        Ent.create({'employe_id': op.id, 'type': 'annuel', 'date': today - relativedelta(months=6), 'evaluateur': "Chef d'atelier — Ligne 2",
                    'evaluation': 'atteint', 'state': 'finalise'})
        e = Ent.create({'employe_id': op.id, 'type': 'annuel', 'date': today, 'evaluateur': "Chef d'atelier — Ligne 2",
                        'evaluation': 'depasse', 'objectifs': 'Préparer une formation de tuteur pour accompagner les nouveaux '
                                                              'opérateurs de la ligne 2 (second semestre).',
                        'ligne_ids': [Command.create({'competence_id': self._ref('kode_agri_rh.comp_1').id, 'niveau_precedent': 'confirme', 'niveau_actuel': 'expert'}),
                                      Command.create({'competence_id': hab.id, 'niveau_actuel': 'acquis'}),
                                      Command.create({'competence_id': self._ref('kode_agri_rh.comp_3').id, 'niveau_precedent': 'debutant', 'niveau_actuel': 'confirme'})]})
        e.action_entretien_manager()
        return 'session %s en cours, entretien de carrière en cours' % s.name
