from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, fields, models

# code, désignation, unité (xmlid uom), prix, stock initial, stock d'alerte, critique
PIECES = [('P-0301', 'Injecteur brûleur', 'uom.product_uom_unit', 78_000, 6, 2, True),
          ('P-0302', 'Joint haute température', 'uom.product_uom_unit', 8_000, 20, 8, False),
          ('P-0310', 'Huile EP220', 'uom.product_uom_litre', 4_500, 60, 20, False),
          ('P-0311', 'Graisse haute température', 'uom.product_uom_kgm', 6_000, 15, 5, False),
          ('P-0320', 'Huile moteur 15W40', 'uom.product_uom_litre', 3_000, 100, 30, False),
          ('P-0321', 'Filtres huile + air + gasoil', 'uom.product_uom_unit', 16_000, 6, 3, False),
          ('P-0322', 'Pneu 315/80 R22.5', 'uom.product_uom_unit', 155_000, 4, 4, True)]


class KaDemoMaintenance(models.AbstractModel):
    _inherit = 'ka.demo'

    def _equipement(self, code):
        return self.env['ka.mnt.equipement'].search([('code', '=', code)], limit=1)

    def _stock(self, product, qty):
        wh = self._entrepot()
        quant = self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': product.id, 'location_id': wh.lot_stock_id.id, 'inventory_quantity': qty})
        quant.action_apply_inventory()

    def _pieces(self):
        categ = self.env.ref('kode_agri_achats.categ_intrants')
        res = {}
        for code, nom, uom, prix, qty, mini, crit in PIECES:
            p = self._product(code, nom, type='consu', is_storable=True, categ_id=categ.id, standard_price=prix,
                              uom_id=self.env.ref(uom).id, uom_po_id=self.env.ref(uom).id) \
                if 'uom_po_id' in self.env['product.product']._fields else \
                self._product(code, nom, type='consu', is_storable=True, categ_id=categ.id, standard_price=prix, uom_id=self.env.ref(uom).id)
            p.product_tmpl_id.write({'ka_piece_mnt': True, 'ka_stock_mini': mini, 'ka_piece_critique': crit})
            if p.qty_available < qty:
                self._stock(p, qty)
            res[code] = p
        return res

    # ---- M10 : maintenance ---------------------------------------------------------------------------------------------------
    def _m10_maintenance(self):
        if self._equipement('EQ-SECH-02'):
            return 'déjà chargé'
        today = date.today()
        pieces = self._pieces()
        E = self.env['ka.mnt.equipement']
        site = self._ref('kode_agri_achats.site_sud')
        equipe = self._ref('kode_agri_maintenance.equipe_sechage')
        tech = self.env['ka.rh.employe'].search([('matricule', '=', 'EMP-0223')], limit=1)
        adjoua = self.env['ka.rh.employe'].search([('matricule', '=', 'EMP-0230')], limit=1)
        equipe.technicien_ids = [Command.set((tech | adjoua).ids)]
        plan_equip = 'kode_agri_gestion.plan_equip'
        immo = self.env['ka.immo'].search([('intitule', '=', 'Séchoir ligne 2')], limit=1)
        atelier = E.create({'code': 'AT-SECH', 'name': 'Atelier séchage', 'designation': 'Atelier séchage', 'niveau': 'atelier',
                            'atelier': 'Séchage', 'site_id': site.id, 'criticite': 'important'})
        sech2 = E.create({
            'code': 'EQ-SECH-02', 'name': 'Séchoir n°2', 'designation': 'Séchoir tunnel n°2', 'niveau': 'machine', 'parent_id': atelier.id,
            'atelier': 'Séchage', 'ligne': 'Ligne 1', 'site_id': site.id, 'workcenter_id': self._ref('kode_agri_production.wc_pc03_02').id,
            'immo_id': immo.id, 'marque': 'DRC Systems', 'modele': 'DT-1200', 'mise_en_service': date(2021, 3, 1), 'criticite': 'critique',
            'equipe_id': equipe.id, 'numero_serie': 'DT1200-21-0458', 'puissance': '450 kW',
            'analytic_id': self._compte_analytique('EQ-SECH-02', 'EQ-SECH-02 — Séchoir n°2', plan_equip).id})
        brul1 = E.create({'code': 'EQ-SECH-02-B1', 'name': 'Brûleur 1', 'designation': 'Brûleur 1', 'niveau': 'sous_ensemble',
                          'parent_id': sech2.id, 'atelier': 'Séchage', 'criticite': 'critique'})
        biom = E.create({'code': 'EQ-SECH-02-BIO', 'name': 'Brûleur biomasse', 'designation': 'Brûleur biomasse', 'niveau': 'sous_ensemble',
                         'parent_id': sech2.id, 'atelier': 'Séchage', 'criticite': 'critique'})
        sech1 = E.create({'code': 'EQ-SECH-01', 'name': 'Séchoir n°1', 'designation': 'Séchoir tunnel n°1', 'parent_id': atelier.id,
                          'atelier': 'Séchage', 'ligne': 'Ligne 1', 'workcenter_id': self._ref('kode_agri_production.wc_pc03_01').id,
                          'criticite': 'critique', 'equipe_id': equipe.id, 'marque': 'DRC Systems', 'modele': 'DT-1200'})
        autres = [E.create({'code': c, 'name': n, 'designation': d, 'atelier': a, 'criticite': k, 'site_id': site.id})
                  for c, n, d, a, k in (('EQ-GRA-150', 'Granulateur GR-150', 'Granulateur GR-150', 'Granulation', 'critique'),
                                        ('EQ-CHAU-01', 'Chaudière biomasse', 'Chaudière biomasse', 'Utilités', 'critique'),
                                        ('EQ-GE-01', 'Groupe électrogène GE-01', 'Groupe électrogène 500 kVA', 'Utilités', 'important'),
                                        ('EQ-GE-02', 'Groupe électrogène GE-02', 'Groupe électrogène 500 kVA', 'Utilités', 'important'),
                                        ('EQ-PONT-01', 'Pont roulant — granulation', 'Pont roulant 10 t', 'Granulation', 'secondaire'))]
        self.env['ka.mnt.releve'].create({'equipement_id': sech2.id, 'type': 'heures', 'valeur': 12_000, 'origine': 'Reprise'})
        # plans préventifs (écran 10.3) : graissage toutes les 500 h, révision trimestrielle, contrôle réglementaire annuel
        P = self.env['ka.mnt.plan']
        gra = P.create({'intitule': 'Graissage paliers', 'equipement_id': sech2.id, 'declencheur': 'heures', 'periodicite': 500,
                        'derniere_valeur': 12_000, 'anticipation': 50, 'duree_estimee': 2,
                        'operation_ids': [Command.create({'name': 'Vidange réducteur', 'product_id': pieces['P-0310'].id, 'quantite': 8}),
                                          Command.create({'name': 'Graissage paliers', 'product_id': pieces['P-0311'].id, 'quantite': 2}),
                                          Command.create({'name': 'Contrôle tension chaîne'})]})
        rev = P.create({'intitule': 'Révision brûleurs', 'equipement_id': sech2.id, 'declencheur': 'calendrier', 'intervalle': 3, 'unite': 'mois',
                        'derniere_date': today - relativedelta(months=1), 'anticipation': 15, 'duree_estimee': 6})
        reg = P.create({'intitule': 'Contrôle réglementaire', 'equipement_id': sech2.id, 'declencheur': 'legal', 'intervalle': 1, 'unite': 'ans',
                        'derniere_date': today - relativedelta(months=4), 'anticipation': 30, 'externe': True})
        (gra | rev | reg).action_activer()
        # relevé de 12 480 h : le seuil d'anticipation du graissage (12 450 h) est franchi → OT préventif automatique (RG-10.1)
        self.env['ka.mnt.releve'].create({'equipement_id': sech2.id, 'type': 'heures', 'valeur': 12_480, 'origine': 'Relevé hebdomadaire'})
        ot_prev = gra.ot_ids[:1]
        # historique : une panne corrigée et clôturée il y a deux mois (indicateurs MTBF / MTTR)
        ancien = self.env['ka.mnt.ot'].create({
            'equipement_id': brul1.id, 'objet': 'Électrode d\'allumage usée', 'type': 'correctif', 'priorite': 'haute',
            'technicien_id': tech.id, 'date_demande': today - relativedelta(months=2), 'duree_arret': 2.5,
            'cause': 'Usure de l\'électrode', 'remede': 'Remplacement de l\'électrode et réglage',
            'ligne_ids': [Command.create({'type': 'main_oeuvre', 'detail': 'Technicien × 2,5 h', 'technicien_id': tech.id, 'quantite': 2.5}),
                          Command.create({'type': 'piece', 'product_id': pieces['P-0302'].id, 'detail': 'Joint haute température', 'quantite': 2})]})
        ancien.action_planifier()
        ancien.action_demarrer()
        ancien.action_cloturer()
        ancien.date_cloture = ancien.date_demande + timedelta(days=1)   # panne réparée le lendemain de la demande
        # demande d'intervention en qualification (écran 10.5)
        di = self.env['ka.mnt.demande'].create({
            'titre': 'Allumage instable — brûleur biomasse', 'equipement_id': sech2.id, 'sous_ensemble_id': biom.id,
            'etat_equipement': 'arret_total', 'equipe_id': equipe.id, 'technicien_id': adjoua.id, 'priorite': '2', 'canal': 'telephone',
            'nature_panne': 'Anomalie de combustion',
            'description': "Le brûleur du séchoir s'éteint de façon intermittente depuis ce matin (3 arrêts en 2 heures). Température "
                           "de séchage instable, risque de non-conformité sur le lot en cours."})
        di.action_qualifier()
        di.message_post(body="Confirmation terrain : allumage instable, forte suspicion de sonde d'allumage défectueuse. Équipement "
                             "critique, arrêt total en cours.")
        # contrats de maintenance (écran 10.6)
        C = self.env['ka.mnt.contrat']
        prest = lambda n: self._partner(n, is_company=True, supplier_rank=1, ka_categorie='frais_generaux')
        contrats = []
        for nom, perim, typ, tarif, unite, debut, fin, eqs in (
                ('AfricTherm Maintenance', 'Séchoir tunnel n°1, n°2', 'intervention', 45_000, 'heure', date(today.year - 1, 3, 1), today + timedelta(days=45), sech1 | sech2),
                ('Ivoire Thermique Services', 'Chaudière biomasse', 'forfait', 850_000, 'trimestre', date(today.year, 1, 1), date(today.year, 12, 31), autres[1]),
                ('SODEM Génie Électrique', 'Groupes électrogènes GE-01/02', 'forfait', 320_000, 'mois', date(today.year, 1, 1), today + timedelta(days=120), autres[2] | autres[3]),
                ('Atlas Levage & Mécanique', 'Pont roulant — granulation', 'intervention', 60_000, 'heure', date(today.year - 1, 7, 1), today - timedelta(days=20), autres[4]),
                ('AfricTherm Maintenance', 'Granulateur GR-150', 'forfait', 410_000, 'trimestre', date(today.year, 3, 1), date(today.year + 1, 2, 28), autres[0])):
            c = C.create({'prestataire_id': prest(nom).id, 'perimetre': perim, 'type': typ, 'tarif': tarif, 'unite_tarif': unite,
                          'date_debut': debut, 'date_fin': fin, 'reconduction': 'oui', 'equipement_ids': [Command.set(eqs.ids)],
                          'sla': '< 24 h si criticité élevée' if typ == 'intervention' else '< 48 h',
                          'contact': 'Yao Brou' if 'AfricTherm' in nom else False, 'telephone': '07 58 xx xx xx' if 'AfricTherm' in nom else False})
            c.action_activer()
            contrats.append(c)
        # OT externalisé sur contrat à l'intervention : demande d'achat → commande → clôture = réception (RG-10.3)
        ext = self.env['ka.mnt.ot'].create({'equipement_id': sech2.id, 'objet': 'Réglage combustion — prestataire', 'type': 'correctif',
                                            'priorite': 'haute', 'contrat_id': contrats[0].id, 'duree_estimee': 4,
                                            'date_demande': today - timedelta(days=20)})
        ext.action_externaliser()
        ext.commande_id.action_signer()
        ext.action_demarrer()
        ext.action_cloturer()
        # OT correctif en cours (écran 10.2)
        demain = fields.Datetime.to_datetime(datetime.combine(today + timedelta(days=1), time(2, 0)))
        ot = self.env['ka.mnt.ot'].create({
            'equipement_id': sech2.id, 'sous_ensemble_id': brul1.id, 'objet': 'brûleur 1 défaillant', 'type': 'correctif',
            'priorite': 'critique', 'technicien_id': tech.id, 'fenetre_debut': demain, 'fenetre_fin': demain + timedelta(hours=4),
            'duree_arret': 3 + 40 / 60.0,
            'ligne_ids': [Command.create({'type': 'main_oeuvre', 'detail': 'Technicien × 3,7 h', 'technicien_id': tech.id, 'quantite': 3.7}),
                          Command.create({'type': 'piece', 'product_id': pieces['P-0301'].id, 'detail': 'Injecteur brûleur (magasin)', 'quantite': 2}),
                          Command.create({'type': 'piece', 'product_id': pieces['P-0302'].id, 'detail': 'Joint haute température', 'quantite': 4})]})
        ot.action_planifier()
        ot.action_demarrer()
        return '%d équipements, 3 plans, OT préventif %s généré au compteur, OT %s en cours, OT externe %s réceptionné, %d contrats' % (
            E.search_count([]), ot_prev.name or '—', ot.name, ext.name, len(contrats))

    # ---- M11 : parc automobile -------------------------------------------------------------------------------------------------
    def _m11_flotte(self):
        V = self.env['ka.flo.vehicule']
        if V.search([('name', '=', 'AA-123-BC')], limit=1):
            return 'déjà chargé'
        today = date.today()
        pieces = self._pieces()
        traore = self.env['ka.rh.employe'].search([('matricule', '=', 'EMP-0150')], limit=1)
        koffi = self.env['ka.rh.employe'].search([('matricule', '=', 'EMP-0151')], limit=1)
        zone = self._compte_analytique('ZONE-SUD', 'Zone Sud', 'kode_agri_gestion.plan_zone')
        immo = self.env['ka.immo'].create({'intitule': 'Camion collecte Renault Kerax AA-123-BC', 'valeur': 72_000_000, 'duree': 5,
                                           'famille_id': self._ref('kode_agri_immo.famille_mattrans').id,
                                           'date_service': today.replace(day=1) - relativedelta(years=3)})
        immo.action_calculer()
        camion = V.create({'name': 'AA-123-BC', 'libelle': 'Camion collecte', 'type': 'camion', 'categorie': 'collecte', 'marque': 'Renault',
                           'modele': 'Kerax', 'annee': today.year - 3, 'charge_utile': 15, 'conducteur_id': traore.id, 'immo_id': immo.id,
                           'analytic_id': self._ref('kode_agri_gestion.an_equip_vh0001').id, 'zone_id': zone.id,
                           'equipe_id': self._ref('kode_agri_maintenance.equipe_sechage').id})
        quatre = V.create({'name': 'AA-456-CD', 'libelle': '4×4 de liaison', 'type': '4x4', 'categorie': 'liaison', 'marque': 'Toyota',
                           'modele': 'Hilux', 'conducteur_id': koffi.id, 'zone_id': zone.id})
        V.create({'name': 'CHE-03', 'libelle': 'Chariot élévateur', 'type': 'chariot', 'categorie': 'manutention', 'marque': 'Toyota',
                  'modele': '8FD30', 'unite_compteur': 'h', 'capacite_levage': 3})
        self.env['ka.flo.releve'].create({'vehicule_id': camion.id, 'valeur': 140_000, 'origine': 'Reprise', 'date': today - timedelta(days=40)})
        self.env['ka.flo.releve'].create({'vehicule_id': quatre.id, 'valeur': 62_300, 'origine': 'Reprise'})
        camion.document_ids = [Command.create({'type': 'assurance', 'reference': 'POL-%s-7741' % today.year, 'date_debut': date(today.year, 1, 1),
                                               'echeance': date(today.year, 12, 31), 'montant': 1_850_000}),
                               Command.create({'type': 'visite_technique', 'reference': 'VT-0912', 'date_debut': today - relativedelta(months=6),
                                               'echeance': today + timedelta(days=20), 'montant': 45_000}),
                               Command.create({'type': 'vignette', 'reference': 'VG-%s' % today.year, 'date_debut': date(today.year, 1, 1),
                                               'echeance': date(today.year, 12, 31), 'montant': 150_000})]
        quatre.document_ids = [Command.create({'type': 'assurance', 'reference': 'POL-%s-7802' % today.year, 'echeance': date(today.year, 12, 31)}),
                               Command.create({'type': 'visite_technique', 'reference': 'VT-0877', 'echeance': today - timedelta(days=5)})]
        plan = self.env['ka.flo.plan'].create({
            'vehicule_id': camion.id, 'intitule': 'Révision des 150 000 km', 'type': 'revision', 'periodicite': 50_000, 'derniere': 100_000,
            'anticipation': 2_000, 'duree_estimee': 4,
            'operation_ids': [Command.create({'name': 'Vidange moteur', 'product_id': pieces['P-0320'].id, 'quantite': 25}),
                              Command.create({'name': 'Filtres', 'product_id': pieces['P-0321'].id, 'quantite': 3}),
                              Command.create({'name': 'Pneumatiques (2 essieux)', 'product_id': pieces['P-0322'].id, 'quantite': 4})]})
        # affectations passées (historique de l'écran 11.5)
        A = self.env['ka.flo.affectation']
        km = 140_000
        for decal, cond, mission, dist in ((6, traore, 'transfert_port', 120), (5, koffi, 'livraison_interne', 40), (4, traore, 'collecte', 90)):
            a = A.create({'vehicule_id': camion.id, 'conducteur_id': cond.id, 'type_mission': mission, 'date': today - timedelta(days=decal),
                          'itineraire': 'Zone Sud' if mission == 'collecte' else 'Abidjan', 'zone_id': zone.id, 'km_depart': km})
            a.action_planifier()
            a.action_demarrer()
            km += dist
            a.km_retour = km
            a.action_terminer()
        # pleins (écran 11.3) : le dernier franchit le seuil d'anticipation de la révision (148 000 km) → ordre d'entretien
        for decal, litres, km_plein, support in ((30, 300, km + 300, 'Carte CARB-014'), (20, 330, 143_180, 'Bon BC-7740'),
                                                 (12, 305, 145_740, 'Carte CARB-014'), (4, 320, 148_320, 'Carte CARB-014')):
            mode, num = support.split(' ')
            self.env['ka.flo.plein'].create({'vehicule_id': camion.id, 'date': today - timedelta(days=decal), 'quantite': litres,
                                             'cout': litres * 640, 'km': km_plein, 'mode': 'carte' if mode == 'Carte' else 'bon',
                                             'support': num})
        # affectation du jour : tournée collecte, terminée, ordre de mission généré (RG-11.6)
        aff = A.create({'vehicule_id': camion.id, 'conducteur_id': traore.id, 'type_mission': 'collecte', 'date': today,
                        'itineraire': 'Zone Sud — 4 points de collecte', 'zone_id': zone.id, 'km_depart': camion.odometre})
        aff.action_planifier()
        aff.action_demarrer()
        aff.km_retour = camion.odometre + 85
        aff.action_terminer()
        jour = fields.Datetime.to_datetime(datetime.combine(today, time(6, 5)))
        aff.write({'depart_reel': jour, 'retour_reel': jour + timedelta(hours=6, minutes=15)})
        aff.action_mission()
        # ordre d'entretien généré au kilométrage, démarré à l'atelier interne (écran 11.2)
        ent = plan.entretien_ids[:1]
        if ent:
            ent.action_planifier()
            ent.action_demarrer()
        # entretien externe par garage ponctuel : demande d'achat validée → appel d'offre (RG-11.2)
        garage = self._partner('Garage Central Daloa', is_company=True, supplier_rank=1, ka_categorie='frais_generaux')
        ext = self.env['ka.flo.entretien'].create({'vehicule_id': quatre.id, 'type': 'reparation', 'declencheur': 'panne',
                                                   'objet': 'Remplacement embrayage', 'realisation': 'garage', 'prestataire_id': garage.id,
                                                   'ligne_ids': [Command.create({'operation': 'Embrayage (forfait garage)', 'quantite': 1,
                                                                                 'prix_unitaire': 380_000})]})
        ext.action_planifier()
        return 'véhicules %s ; %d pleins ; entretien %s ; affectation %s → ordre de mission %s ; entretien externe %s (%s)' % (
            ', '.join(V.search([]).mapped('name')), len(camion.plein_ids), ent.name or '—', aff.name, aff.mission_id.name,
            ext.name, ext.ao_id.name or ext.da_id.name or '—')
