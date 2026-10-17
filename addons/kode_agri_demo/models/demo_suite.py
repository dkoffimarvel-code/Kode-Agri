from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, fields, models


class KaDemoSuite(models.AbstractModel):
    _inherit = 'ka.demo'

    # ---- M5 : vente et logistique export ---------------------------------------------------------------------------------
    def _m5_vente(self):
        if self.env['ka.contrat'].search([('ref_client', '=', 'TC-EXP-2026-118')], limit=1):
            return 'déjà chargé'
        today = date.today()
        tsr10 = self._ref('kode_agri_production.product_tsr10')
        usine = self._entrepot()
        contrat = self.env['ka.contrat'].create({
            'type': 'clt', 'partner_id': self.tyre.id, 'product_id': tsr10.id, 'tracabilite': 'eudr', 'qty_kg': 1_008_000, 'prix_t': 1150,
            'periode': 'Juillet %s' % today.year, 'incoterm': 'FOB Abidjan', 'ref_client': 'TC-EXP-2026-118', 'paiement': 'remise_doc',
            'emballage': 'palette', 'warehouse_id': usine.id})
        contrat.action_soumettre()
        contrat.action_signer()
        spot = self.env['ka.contrat'].create({
            'type': 'spot', 'partner_id': self._partner('RubberTrade SA').id, 'product_id': self._ref('kode_agri_production.product_tsr20').id,
            'tracabilite': 'eudr', 'qty_kg': 40_000, 'prix_t': 1080, 'periode': 'Août %s' % today.year, 'incoterm': 'CFR Le Havre', 'ref_client': 'RT-SPOT-77'})
        spot.action_soumettre()
        france = self.env.ref('base.fr')
        sc = self.env['ka.sous.contrat'].create({
            'contrat_id': contrat.id, 'warehouse_id': usine.id, 'product_id': tsr10.id, 'poids_kg': 40320, 'conditionnement': 'palette',
            'marquage': 'TC / TSR10 / FR', 'country_id': france.id, 'doc_phyto_requis': True, 'certificat_garantie': True, 'paiement': 'prefinancement',
            'armateur': 'MAERSK', 'transitaire_id': self._partner('Ivoire Transit & Douane').id, 'navire': 'MV Adrian Maersk', 'voyage_no': 'V-%s-118' % today.year,
            'booking': 'BKG-0061-03', 'bmc': 'BMC-0061-03', 'date_embarquement_prevue': today + timedelta(days=11),
            'date_fermeture_navire': today + timedelta(days=9), 'banque': 'SGBCI', 'shipper': 'EXAT SA', 'notify1': 'TyreCorp Ltd',
            'consignee': 'TyreCorp Ltd', 'description_marchandise': 'Caoutchouc naturel TSR10 — 2 conteneurs'})
        sc.action_instructions()
        sc.action_valider_booking()
        voyage = self.env['ka.voyage'].create({
            'transporteur_id': self._partner('Sahel Log').id, 'vehicule': 'AA-7741-CI', 'type_transport': 'bitrain', 'warehouse_id': usine.id,
            'date_prise_prevue': today + timedelta(days=3), 'date_chargement_prevu': today + timedelta(days=4),
            'parc_armateur': 'Parc MAERSK — Abidjan', 'parc_terre_plein': 'Terre-plein AKF — Abidjan',
            'line_ids': [Command.create({'sous_contrat_id': sc.id}), Command.create({'sous_contrat_id': sc.id})],
            'conteneur_ids': [Command.create({'serie': 'MSKU-77412%02d' % (30 + i), 'sous_contrat_id': sc.id, 'plomb': 'PLB-5582%02d' % (17 + i),
                                              'armateur': 'MAERSK', 'tare': 2180 + 10 * i, 'date_entree_parc': today + timedelta(days=3)}) for i in range(2)]})
        voyage.action_valider_affectation()
        ctn = voyage.conteneur_ids[0]
        ctn.action_allouer()            # 16 colis TSR10 libérés, conformes aux spécifications du contrat
        ctn.action_empoter()
        liv = self.env['ka.livraison'].create({'conteneur_id': ctn.id, 'voyage_id': voyage.id, 'transporteur_id': voyage.transporteur_id.id,
                                               'immatriculation': voyage.vehicule, 'chauffeur': 'Traoré Issa'})
        liv.action_valider()
        sc.write({'decl_numero': 'DE-%s-31842' % today.year, 'decl_date': today})
        sc.action_generer_dus()
        sc.action_generer_parafiscalite()
        return 'contrat Long terme signé, contrat Spot à signer, sous-contrat booké, voyage, %d colis empotés, DUS et parafiscalité' % len(ctn.colis_ids)

    # ---- M6 : note de frais -------------------------------------------------------------------------------------------------
    def _m6_frais(self):
        if self.env['ka.frais.note'].search([('intitule', '=', 'Tournée collecte Sud')], limit=1):
            return 'déjà chargé'
        today = date.today()
        lundi = today - timedelta(days=today.weekday() + 7)
        cat = lambda c: self._ref('kode_agri_frais.cat_%s' % c)
        note = self.env['ka.frais.note'].create({
            'intitule': 'Tournée collecte Sud', 'salarie_id': self.agent.id, 'date_debut': lundi, 'date_fin': lundi + timedelta(days=4),
            'analytic_id': self._ref('kode_agri_frais.analytic_colsud').id,
            'line_ids': [Command.create({'date': lundi, 'categorie_id': cat('carb').id, 'description': 'Plein véhicule collecte', 'justificatif': True, 'montant': 45000}),
                         Command.create({'date': lundi + timedelta(days=1), 'categorie_id': cat('rest').id, 'description': 'Mission terrain', 'justificatif': True, 'montant': 12500}),
                         Command.create({'date': lundi + timedelta(days=2), 'categorie_id': cat('heb').id, 'description': 'Nuitée Daloa', 'justificatif': True, 'montant': 39000})]})
        note.action_soumettre()
        note.action_approuver()
        note.action_comptabiliser()
        return 'note %s de %s FCFA comptabilisée' % (note.name, '{:,.0f}'.format(note.total).replace(',', ' '))

    # ---- M2 : achats et stock ---------------------------------------------------------------------------------------------------
    def _m2_achats(self):
        if self.env['ka.da'].search([('objet', '=', 'Pièces de rechange séchoir')], limit=1):
            return 'déjà chargé'
        today = date.today()
        site = self._ref('kode_agri_achats.site_sud')
        wh = self._entrepot()
        roulement, courroie = self._product('P-0231', 'Roulement 9120'), self._product('P-0244', 'Courroie transporteur')
        da = self.env['ka.da'].create({
            'objet': 'Pièces de rechange séchoir', 'site_id': site.id, 'demandeur': 'Service maintenance', 'date_besoin': today + timedelta(days=14), 'depot_id': wh.id,
            'line_ids': [Command.create({'product_id': roulement.id, 'qty': 4, 'montant': 320000, 'designation': roulement.name}),
                         Command.create({'product_id': courroie.id, 'qty': 6, 'montant': 180000, 'designation': courroie.name})]})
        da.action_soumettre()
        da.action_signer()
        da.action_demande_prix()
        ao = da.ao_ids[:1] or self.env['ka.ao'].search([('da_id', '=', da.id)], limit=1)
        prix = [(78000, 28000, 7), (82000, 26000, 12), (88000, 31000, 5)]
        for offre, (p1, p2, delai) in zip(ao.offre_ids, prix):
            offre.delai = delai
            for lg, p in zip(offre.ligne_ids, (p1, p2)):
                lg.prix = p
        ao.action_retenir()
        ao.action_generer_commande()
        cmd = ao.commande_id
        cmd.action_soumettre()
        cmd.action_signer()
        cmd.action_creer_reception()
        rec = cmd.reception_ids[:1]
        for l in rec.line_ids:                   # réception partielle : la courroie n'est reçue qu'en partie
            l.recu = l.commande if l.product_id == roulement else 4
        rec.action_valider()
        fac = self.env['ka.facture'].create({'commande_id': cmd.id})
        fac.doc_ids.write({'fourni': True})
        fac.action_valider()
        # dossier d'import avec ventilation des frais d'approche
        imp = self.env['ka.dossier.import'].create({
            'partner_id': self._partner('Vatscan Trading Ltd (NL)').id, 'transitaire_id': self._partner('Bolloré Logistics CI').id, 'site_id': site.id,
            'line_ids': [Command.create({'product_id': self._product('INT-CHM-0042', 'Coagulant acide formique').id, 'qty': 12000, 'poids': 12000, 'fob': 9_180_000}),
                         Command.create({'product_id': self._product('INT-FILM', 'Film polyéthylène emballage').id, 'qty': 450, 'poids': 900, 'fob': 3_240_000}),
                         Command.create({'product_id': self._product('P-0250', 'Filtre').id, 'qty': 3, 'poids': 300, 'fob': 2_580_000})],
            'frais_ids': [Command.create({'type': 'transport', 'libelle': 'Fret maritime', 'facture_ref': 'BOL-7741', 'montant': 1_100_000}),
                          Command.create({'type': 'douane', 'libelle': 'Droits de douane', 'facture_ref': 'BOL-7742', 'montant': 600_000}),
                          Command.create({'type': 'assurance', 'libelle': 'Assurance transport', 'facture_ref': 'BOL-7743', 'montant': 171_250})]})
        imp.action_ventiler()
        # transfert et inventaire
        autre = self.env['stock.warehouse'].search([('id', '!=', wh.id)], limit=1) or wh
        self.env['ka.transfert'].create({'emetteur_id': wh.id, 'destinataire_id': autre.id, 'date_prevue': today, 'line_ids': [Command.create({'product_id': roulement.id, 'qty': 1})]})
        self.env['ka.inventaire'].create({'depot_id': wh.id, 'line_ids': [Command.create({'product_id': roulement.id, 'location_id': wh.lot_stock_id.id, 'theorique': 4, 'compte': 4}),
                                                                        Command.create({'product_id': courroie.id, 'location_id': wh.lot_stock_id.id, 'theorique': 4, 'compte': 3})]})
        return 'DA → AO → commande → réception partielle → facture ; dossier d\'import ventilé (%s FCFA de frais)' % '{:,.0f}'.format(imp.total_frais).replace(',', ' ')

    # ---- M3 : immobilisations -------------------------------------------------------------------------------------------------------
    def _m3_immo(self):
        if self.env['ka.immo'].search([('intitule', '=', 'Séchoir ligne 2')], limit=1):
            return 'déjà chargé'
        today = date.today()
        eq = self._ref('kode_agri_immo.famille_eqtrans')
        site = self._ref('kode_agri_achats.site_sud')
        mois_prec = today.replace(day=1) - relativedelta(months=1)
        fin_mois_prec = today.replace(day=1) - timedelta(days=1)
        parc = [('Séchoir ligne 2', 40_000_000, 120, 'an_l2_sechage'), ('Séchoir ligne 3', 54_000_000, 120, 'an_l3_sechage'),
                ('Presse à balles n° 1', 43_200_000, 96, 'an_l2_pressage')]
        for nom, valeur, mois, section in parc:      # dotations mensuelles : 333 333 + 450 000 + 450 000 = 1 233 333
            im = self.env['ka.immo'].create({'intitule': nom, 'famille_id': eq.id, 'valeur': valeur, 'duree': mois // 12, 'date_service': mois_prec,
                                             'site_id': site.id, 'analytic_id': self._ref('kode_agri_immo.%s' % section).id})
            im.action_calculer()
        dot = self.env['ka.immo.dotation'].create({'periode': fin_mois_prec, 'date_piece': fin_mois_prec})
        dot.action_simuler()
        dot.action_comptabiliser()
        # créées après la dotation : leurs échéances restent à comptabiliser, la sortie rattrape celles du laminoir
        self.env['ka.immo'].create({'intitule': 'Presse à balles n° 2', 'famille_id': eq.id, 'valeur': 28_500_000, 'duree': 8, 'date_service': today.replace(day=1),
                                    'site_id': site.id, 'analytic_id': self._ref('kode_agri_immo.an_l2_pressage').id}).action_calculer()
        laminoir = self.env['ka.immo'].create({'intitule': 'Laminoir 1', 'famille_id': eq.id, 'valeur': 6_700_000, 'duree': 10, 'date_service': date(today.year - 4, 1, 1), 'site_id': site.id})
        laminoir.action_calculer()
        self.env['ka.immo.sortie'].create({'immo_id': laminoir.id, 'type': 'cession', 'date': today, 'prix': 4_500_000,
                                           'partner_id': self._partner('CLI-0412 Acquéreur de matériel').id})
        return '4 immobilisations, dotation %s comptabilisée (%s FCFA), 1 cession à valider' % (
            fin_mois_prec.strftime('%m/%Y'), '{:,.0f}'.format(dot.total).replace(',', ' '))

    # ---- M7 : comptabilité et finance -------------------------------------------------------------------------------------------------
    def _m7_compta(self):
        today = date.today()
        usd = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
        tsr10 = self._ref('kode_agri_production.product_tsr10')
        contrat = self.env['ka.contrat'].search([('ref_client', '=', 'TC-EXP-2026-118')], limit=1)
        if not self.env['account.move'].search([('ka_contrat_id', '!=', False)], limit=1):
            self.env['account.move'].create({
                'move_type': 'out_invoice', 'partner_id': self.tyre.id, 'invoice_date': today, 'currency_id': usd.id, 'ka_contrat_id': contrat.id,
                'ka_site_id': self._ref('kode_agri_achats.site_sud').id,
                'invoice_line_ids': [Command.create({'product_id': tsr10.id, 'name': 'Caoutchouc TSR10 — 16 colis', 'quantity': 20.16, 'price_unit': 1250})]})
        facture = self.env['account.move'].search([('move_type', '=', 'in_invoice')], limit=1)
        if facture and not self.env['ka.rapprochement'].search([('move_id', '=', facture.id)], limit=1):
            self.env['ka.rapprochement'].create({'move_id': facture.id})
        for i, (rub, montant, libelle) in enumerate([('emprunts', 4_500_000, 'Échéance emprunt campagne'), ('impots', 5_800_000, 'TVA et taxes du mois'),
                                                      ('spots', 6_000_000, 'Remboursement spot'), ('personnel', 7_300_000, 'Paie du mois')]):
            if not self.env['ka.treso.ligne'].search([('libelle', '=', libelle)], limit=1):
                self.env['ka.treso.ligne'].create({'date': today + timedelta(days=5 + 7 * i), 'rubrique': rub, 'montant': montant, 'libelle': libelle})
        if not self.env['ka.regul'].search([], limit=1):
            self.env['ka.regul'].create({'type': 'cca', 'libelle': "Prime d'assurance annuelle", 'date_cloture': date(today.year, 12, 31), 'montant': 1_200_000,
                                         'compte_charge_id': self._compte('627100').id, 'compte_regul_id': self._compte('476').id})
        pl = self.planteurs[0]
        compte = self.env['account.account'].search([('account_type', '=', 'liability_payable')], limit=1)
        if compte and not self.env['ka.lettrage'].search([('partner_id', '=', pl.id)], limit=1):
            self.env['ka.lettrage'].create({'account_id': compte.id, 'partner_id': pl.id}).action_proposer()
        return 'facture export USD, contrôle de facture, prévisions manuelles, CCA, lettrage'
