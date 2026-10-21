from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'kode_agri')
class TestModulesV45(TransactionCase):
    """Règles de gestion des modules ajoutés en v4.5 : RH et paie (7), maintenance (10), parc automobile (11)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.aff = env.ref('kode_agri_rh.aff_2')
        cls.cat = env.ref('kode_agri_rh.cat_1')
        cls.base = env['ka.rh.rubrique'].par_code('BASE')

        def employe(mat, mois, salaire=185_000, **kw):
            e = env['ka.rh.employe'].create(dict({
                'matricule': mat, 'name': 'Test %s' % mat, 'poste': 'Opérateur séchage', 'affectation_id': cls.aff.id,
                'categorie_id': cls.cat.id, 'date_entree': date.today() - relativedelta(months=mois), 'badge': 'T-%s' % mat,
                'element_ids': [Command.create({'rubrique_id': cls.base.id, 'type': 'fixe_mensuel', 'montant': salaire})]}, **kw))
            e.action_activer()
            return e
        cls.employe = staticmethod(employe)
        cls.op = employe('TST-001', 30)

    # ---- module 7 ------------------------------------------------------------------------------------------------------------
    def test_its_bareme_progressif(self):
        its = self.env['ka.rh.its.tranche'].calculer(216_260, date(2026, 6, 1))
        self.assertEqual(its, round((216_260 - 75_000) * 0.16))
        self.assertEqual(self.env['ka.rh.its.tranche'].calculer(70_000, date(2026, 6, 1)), 0)

    def test_bulletin_cascade(self):
        b = self.env['ka.rh.bulletin'].create({'employe_id': self.op.id, 'periode': date.today().replace(day=1)})
        b.action_calculer()
        self.assertEqual(b.brut, 185_000)
        self.assertEqual(b.cotisations, round(185_000 * 0.063))   # retraite salariale 6,3 %, sous le plafond
        self.assertEqual(round(b.net), round(b.brut - b.cotisations - b.its - b.autres_retenues))
        self.assertTrue(b.charges_patronales > 0)
        b.action_confirmer()
        with self.assertRaises(UserError):   # RG-7.4 : un bulletin confirmé n'est jamais recalculé
            b.action_calculer()

    def test_rg71_anomalie_bloque_la_paie(self):
        lundi = date.today() - timedelta(days=date.today().weekday() + 7)
        f = self.env['ka.rh.feuille'].create({'employe_id': self.op.id, 'date_debut': lundi,
                                              'ligne_ids': [Command.create({'date': lundi, 'entree': 7, 'sortie': 15})]})
        f.action_controler()
        self.assertEqual(f.nb_anomalies, 4)   # mardi à vendredi sans pointage
        with self.assertRaises(UserError):
            f.action_valider()
        for l in f.ligne_ids.filtered(lambda x: x.anomalie != 'aucune'):
            l.motif_regul = 'Absence justifiée'
        f.action_regulariser()
        f.action_valider()
        self.assertEqual(f.state, 'validee')

    def test_pointeuse_api_doublon(self):
        Evt = self.env['ka.rh.pointage.event']
        h = '2026-06-15 06:58:00'
        res = Evt.recevoir([{'identifiant': self.op.badge, 'horodatage': h, 'sens': 'entree'},
                            {'identifiant': 'INCONNU', 'horodatage': h, 'sens': 'entree'}])
        self.assertEqual((res['rapproche'], res['rejete']), (1, 1))
        res = Evt.recevoir([{'identifiant': self.op.badge, 'horodatage': '2026-06-15 06:59:00', 'sens': 'entree'}])
        self.assertEqual(res['anomalie'], 1)

    def test_rg72_conge_annuel_apres_douze_mois(self):
        jeune = self.employe('TST-002', 6)
        d = self.env['ka.rh.demande'].create({'type_demande': 'conge', 'employe_id': jeune.id,
                                              'type_conge_id': self.env.ref('kode_agri_rh.tc_ca').id,
                                              'date_debut': date.today() + timedelta(days=30), 'date_fin': date.today() + timedelta(days=32)})
        with self.assertRaises(UserError):
            d.action_soumettre()

    def test_rg73_permission_plafond(self):
        lundi = date(date.today().year, 3, 2)
        perm = lambda debut, fin: self.env['ka.rh.demande'].create({
            'type_demande': 'permission', 'employe_id': self.op.id, 'evenement': 'deces', 'foyer': True,
            'date_debut': debut, 'date_fin': fin})
        p1 = perm(lundi, lundi + timedelta(days=20))   # au moins 14 jours ouvrés : le plafond de 10 jours est atteint
        p1.action_soumettre()
        p1.action_approuver()
        p1.action_approuver()
        p2 = perm(lundi + timedelta(days=21), lundi + timedelta(days=22))
        self.assertEqual(p2.jours_non_remuneres, p2.duree)   # au-delà du plafond annuel : non rémunérée

    def test_rg76_rg77_recrutement(self):
        dp = self.env['ka.rh.demande.personnel'].create({'poste': 'Opérateur', 'affectation_id': self.aff.id, 'demandeur': 'Chef',
                                                        'motif': 'creation', 'budget': 185_000, 'categorie_id': self.cat.id})
        with self.assertRaises(ValidationError):   # RG-7.6 : pas de candidature sans demande approuvée
            self.env['ka.rh.candidature'].create({'name': 'X', 'demande_id': dp.id})
        dp.action_soumettre()
        dp.action_valider()
        dp.action_valider()
        self.assertEqual(dp.state, 'a_valider')   # création de poste : la direction valide toujours
        dp.action_valider()
        self.assertEqual(dp.state, 'approuvee')
        with self.assertRaises(ValidationError):   # RG-7.7 : essai au-delà du maximum de la catégorie (1 mois)
            self.employe('TST-003', 0, essai_mois=3)

    def test_rg78_competence_apres_formation(self):
        comp = self.env.ref('kode_agri_rh.comp_2')
        s = self.env['ka.rh.session'].create({'intitule': 'Habilitation', 'date_debut': date.today(), 'date_fin': date.today(),
                                              'competence_id': comp.id, 'niveau_vise': 'acquis',
                                              'participant_ids': [Command.create({'employe_id': self.op.id, 'resultat': 'valide'})]})
        s.action_cloturer()
        self.assertEqual(self.op.competence_ids.filtered(lambda c: c.competence_id == comp).niveau, 'acquis')

    # ---- module 10 -----------------------------------------------------------------------------------------------------------
    def _machine(self, code='TST-EQ'):
        return self.env['ka.mnt.equipement'].create({'code': code, 'name': 'Machine test', 'designation': 'Machine test',
                                                     'atelier': 'Séchage', 'criticite': 'critique'})

    def test_rg101_ot_preventif_sur_compteur(self):
        m = self._machine()
        self.env['ka.mnt.releve'].create({'equipement_id': m.id, 'type': 'heures', 'valeur': 1_000})
        plan = self.env['ka.mnt.plan'].create({'intitule': 'Graissage', 'equipement_id': m.id, 'declencheur': 'heures',
                                               'periodicite': 500, 'anticipation': 50})
        plan.action_activer()
        self.assertEqual(plan.prochaine_valeur, 1_500)
        self.env['ka.mnt.releve'].create({'equipement_id': m.id, 'type': 'heures', 'valeur': 1_460})
        self.assertEqual(len(plan.ot_ids), 1)
        self.assertEqual(plan.ot_ids.type, 'preventif')
        self.env['ka.mnt.releve'].create({'equipement_id': m.id, 'type': 'heures', 'valeur': 1_480})
        self.assertEqual(len(plan.ot_ids), 1)   # pas de doublon tant que l'OT est ouvert

    def test_rg103_ot_externe_exige_commande_approuvee(self):
        m = self._machine('TST-EQ2')
        c = self.env['ka.mnt.contrat'].create({'prestataire_id': self.env['res.partner'].create({'name': 'Prest'}).id, 'tarif': 45_000,
                                               'date_debut': date.today(), 'date_fin': date.today() + relativedelta(years=1),
                                               'equipement_ids': [Command.set(m.ids)]})
        c.action_activer()
        ot = self.env['ka.mnt.ot'].create({'equipement_id': m.id, 'objet': 'Réglage', 'contrat_id': c.id, 'duree_estimee': 2})
        ot.action_externaliser()
        self.assertTrue(ot.commande_id)
        ot.action_demarrer()
        with self.assertRaises(UserError):
            ot.action_cloturer()

    # ---- module 11 -----------------------------------------------------------------------------------------------------------
    def test_carburant_et_rg115_rg116(self):
        V = self.env['ka.flo.vehicule']
        v = V.create({'name': 'TST-001-AA', 'type': 'camion', 'categorie': 'collecte'})
        self.env['ka.flo.plein'].create({'vehicule_id': v.id, 'quantite': 100, 'cout': 64_000, 'km': 10_000})
        p = self.env['ka.flo.plein'].create({'vehicule_id': v.id, 'quantite': 120, 'cout': 76_800, 'km': 11_000})
        self.assertAlmostEqual(p.conso, 12.0)
        self.assertEqual(v.odometre, 11_000)
        chauffeur = self.employe('TST-004', 24)
        A = self.env['ka.flo.affectation']
        a1 = A.create({'vehicule_id': v.id, 'conducteur_id': chauffeur.id, 'km_depart': 11_000})
        a1.action_demarrer()
        a2 = A.create({'vehicule_id': v.id, 'conducteur_id': chauffeur.id})
        with self.assertRaises(UserError):   # RG-11.5 : une seule affectation active
            a2.action_demarrer()
        with self.assertRaises(UserError):   # RG-11.6 : mission seulement après la tournée
            a1.action_mission()
        a1.km_retour = 11_085
        a1.action_terminer()
        a1.action_mission()
        self.assertEqual(a1.mission_id.employe_id, chauffeur)
        with self.assertRaises(UserError):
            a1.action_mission()

    def test_document_echu_bloque_affectation(self):
        v = self.env['ka.flo.vehicule'].create({'name': 'TST-002-AA', 'type': 'camion', 'categorie': 'collecte',
                                                'document_ids': [Command.create({'type': 'assurance', 'echeance': date.today() - timedelta(days=1)})]})
        a = self.env['ka.flo.affectation'].create({'vehicule_id': v.id, 'conducteur_id': self.op.id})
        with self.assertRaises(UserError):
            a.action_planifier()
