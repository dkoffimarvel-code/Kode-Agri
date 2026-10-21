"""Chargeur de démonstration Kode Agri.

Chaque étape passe par les vrais traitements des modules (import de tickets, génération des commandes, déclaration des
colis, signature des contrats…) : si une étape échoue, c'est qu'un flux est cassé ; l'erreur est journalisée avec son
contexte et les étapes suivantes continuent. Relancer le chargement est sans danger (les étapes déjà faites sont sautées) :

    odoo shell -d MABASE <<< "print(env['ka.demo'].charger())"
"""
import base64
import logging
import traceback
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models

_logger = logging.getLogger(__name__)

COMPTES = [  # code, intitulé, type
    ('2154', 'Matériel industriel', 'asset_fixed'), ('28154', 'Amort. matériel industriel', 'asset_fixed'),
    ('2184', 'Matériel de transport', 'asset_fixed'), ('28184', 'Amort. matériel de transport', 'asset_fixed'),
    ('2131', 'Bâtiments industriels', 'asset_fixed'), ('28131', 'Amort. bâtiments industriels', 'asset_fixed'),
    ('68112', 'Dotation amortissements', 'expense_depreciation'),
    ('811', 'Valeurs comptables des cessions', 'expense'), ('821', 'Produits des cessions', 'income_other'),
    ('421000', 'Personnel — notes de frais à payer', 'liability_payable'),
    ('605100', 'Carburant', 'expense'), ('605200', 'Fournitures', 'expense'), ('622500', 'Restauration', 'expense'),
    ('622600', 'Hébergement', 'expense'), ('476', "Charges constatées d'avance", 'asset_current'),
    ('477', "Produits constatés d'avance", 'liability_current'), ('4081', 'Fournisseurs — factures non parvenues', 'liability_current'),
    ('4181', 'Clients — produits à recevoir', 'asset_current'), ('4851', 'Créances sur cessions', 'asset_current'),
    ('601100', 'Achats FDT', 'expense'), ('613200', 'Énergie', 'expense'), ('641100', 'Salaires production', 'expense'),
    ('624100', 'Transport / transit', 'expense'), ('627100', 'Frais bancaires', 'expense'), ('641200', 'Salaires structure', 'expense'),
    ('602200', 'Carburant', 'expense'), ('602400', 'Pneumatiques', 'expense'), ('615500', 'Entretien', 'expense'),
    ('2411100', 'Matériel et outillage industriel', 'asset_fixed'),
    # paie (module 7), missions, carburant (module 11)
    ('661100', 'Rémunérations directes versées au personnel', 'expense'), ('664100', 'Charges sociales', 'expense'),
    ('641300', 'Taxes sur appointements et salaires (FDFP)', 'expense'), ('422000', 'Personnel, rémunérations dues', 'liability_current'),
    ('421100', 'Personnel, avances et acomptes', 'asset_current'), ('431000', 'Sécurité sociale (CNPS)', 'liability_current'),
    ('447200', 'État, impôts retenus à la source (ITS)', 'liability_current'),
    ('447800', 'État, autres impôts et contributions (FDFP)', 'liability_current'), ('618100', 'Voyages et déplacements', 'expense'),
    ('604200', 'Matières combustibles (carburant)', 'expense'),
]


class KaDemo(models.AbstractModel):
    _name = 'ka.demo'
    _description = 'Chargeur de démonstration Kode Agri'

    # ------------------------------------------------------------------------------------------------------------
    @api.model
    def charger(self):
        """Exécute toutes les étapes ; retourne le rapport (texte)."""
        etapes = [
            ('Contexte (société, devises, comptes, journaux)', self._contexte),
            ('Tiers et articles', self._base),
            ('M1 — Tarifs, primes, avances', self._m1_parametres),
            ('M1 — Tickets de pesée → commandes → réceptions → factures', self._m1_flux),
            ('M4 — Mélange, production, paniers, colis, spécifications, libération', self._m4_production),
            ('M5 — Contrat, sous-contrat, voyage, empotage, export', self._m5_vente),
            ('M6 — Note de frais', self._m6_frais),
            ('M2 — Demande d\'achat, appel d\'offres, commande, réception, facture, dossier d\'import', self._m2_achats),
            ('M3 — Immobilisations, dotations, sortie', self._m3_immo),
            ('M8 — Facture export, contrôle facture, trésorerie, régularisation', self._m8_compta),
            ('M9 — Analytique, budget, CAPEX, unités d\'œuvre', self._m9_gestion),
            ('M7 — Personnel, pointage, congés, paie, missions, recrutement, formation', self._m7_rh),
            ('M10 — Équipements, plans préventifs, OT, demandes d\'intervention, contrats', self._m10_maintenance),
            ('M11 — Véhicules, documents, carburant, affectations, entretien', self._m11_flotte),
        ]
        rapport = []
        for nom, fn in etapes:
            try:
                with self.env.cr.savepoint():
                    detail = fn() or ''
                rapport.append('OK    %s %s' % (nom, ('— ' + detail) if detail else ''))
            except Exception as e:  # noqa: BLE001 — on veut tout capter pour rapporter
                _logger.warning('Démo Kode Agri — échec de l\'étape « %s » : %s\n%s', nom, e, traceback.format_exc())
                rapport.append('ÉCHEC %s — %s: %s' % (nom, type(e).__name__, str(e).strip().splitlines()[0] if str(e).strip() else ''))
        texte = '\n'.join(rapport)
        _logger.info('Démo Kode Agri — rapport :\n%s', texte)
        self.env['ir.config_parameter'].sudo().set_param('kode_agri.demo_rapport', texte)
        return texte

    # ---- utilitaires -------------------------------------------------------------------------------------------------
    def _ref(self, xmlid):
        return self.env.ref(xmlid)

    def _partner(self, name, **vals):
        p = self.env['res.partner'].search([('name', '=', name)], limit=1)
        return p or self.env['res.partner'].create(dict(vals, name=name))

    def _product(self, code, name, **vals):
        p = self.env['product.product'].search([('default_code', '=', code)], limit=1)
        return p or self.env['product.product'].create(dict(vals, default_code=code, name=name))

    def _compte(self, code):
        return self.env['account.account'].search([('code', '=', code)], limit=1)

    def _analytique(self, code):
        return self.env['account.analytic.account'].search([('code', '=', code)], limit=1)

    def _entrepot(self):
        return self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)

    # ---- 0. contexte -----------------------------------------------------------------------------------------------------
    def _contexte(self):
        msgs = []
        societe = self.env.company
        if societe.currency_id.name != 'XOF':
            msgs.append('ATTENTION : la devise de la société est %s, pas XOF — créez la base avec le pays Côte d\'Ivoire' % societe.currency_id.name)
        else:
            for code, taux in (('EUR', 655.957), ('USD', 610.0)):
                cur = self.env['res.currency'].with_context(active_test=False).search([('name', '=', code)], limit=1)
                if cur:
                    cur.active = True
                    if not self.env['res.currency.rate'].search([('currency_id', '=', cur.id), ('company_id', '=', societe.id)], limit=1):
                        self.env['res.currency.rate'].create({'currency_id': cur.id, 'name': date.today().replace(month=1, day=1), 'rate': 1.0 / taux, 'company_id': societe.id})
        crees = 0
        for code, nom, typ in COMPTES:
            if not self._compte(code):
                self.env['account.account'].create({'code': code, 'name': nom, 'account_type': typ})
                crees += 1
        msgs.append('%d compte(s) créé(s)' % crees)
        for code, nom, typ, dev in (('BNK1', 'SGBCI — compte d\'exploitation', 'bank', None), ('CSH1', 'Caisse', 'cash', None), ('BNK2', 'Compte devises USD', 'bank', 'USD')):
            if not self.env['account.journal'].search([('code', '=', code)], limit=1):
                vals = {'name': nom, 'code': code, 'type': typ}
                if dev:
                    cur = self.env['res.currency'].search([('name', '=', dev)], limit=1)
                    vals['currency_id'] = cur.id
                try:
                    with self.env.cr.savepoint():
                        self.env['account.journal'].create(vals)
                except Exception as e:  # noqa: BLE001
                    msgs.append('journal %s non créé (%s)' % (code, str(e).splitlines()[0]))
        return '; '.join(msgs)

    # ---- tiers et articles --------------------------------------------------------------------------------------------------
    def _base(self):
        P = self.env['res.partner']
        self.coop = self._partner('Coopérative COOPAGRI Dabou', is_company=True, ka_categorie='planteur_coop', ka_mode_reglement='vir', supplier_rank=1)
        self.planteurs = [self._partner(n, ka_categorie='planteur_coop', ka_cooperative_id=self.coop.id if i == 0 else False,
                                        ka_mode_reglement='vir' if i < 2 else 'chq', supplier_rank=1)
                          for i, n in enumerate(["Kouassi N'Guessan", 'Aya Koffi', 'Traoré Issa'])]
        for p in self.planteurs[:2]:
            if not p.ka_parcelle_ids:
                p.ka_parcelle_ids = [Command.create({'name': 'PARC-%s-%d' % (p.ka_code, k), 'surface': 4.5 + k, 'latitude': 5.3 + k / 100, 'longitude': -4.0 - k / 100,
                                                     'clone': 'GT1', 'statut_eudr': 'conforme' if k == 0 else 'a_verifier'}) for k in range(2)]
        for n, cat in (('Chimie Ivoire SA', 'frais_generaux'), ('Sté Industrielle CI', 'frais_generaux'), ('Equip Abidjan', 'frais_generaux'),
                       ('Tech Supply', 'frais_generaux'), ('Vatscan Trading Ltd (NL)', 'frais_generaux'), ('Bolloré Logistics CI', 'transitaire'),
                       ('Ivoire Transit & Douane', 'transitaire'), ('Sahel Log', 'transitaire')):
            self._partner(n, is_company=True, ka_categorie=cat, supplier_rank=1)
        self.tyre = self._partner('TyreCorp Ltd', is_company=True, ka_client=True, customer_rank=1, ka_cat_client='export', ka_incoterm='FOB Abidjan', ka_paiement='remise_doc')
        if not self.tyre.ka_spec_ids:
            specs = {'p0': ('30', None), 'pri': ('50', None), 'ml': ('65', '85'), 'vm': (None, '0,80'), 'azote': (None, '0,60'), 'cendres': (None, '0,75'), 'imp': (None, '0,10')}
            self.tyre.ka_spec_ids = [Command.create({'test': t, 'vmin': a, 'vmax': b}) for t, (a, b) in specs.items()]
        self._partner('RubberTrade SA', is_company=True, ka_client=True, customer_rank=1, ka_cat_client='export')
        self._partner('Pneus du Sahel SARL', is_company=True, ka_client=True, customer_rank=1, ka_cat_client='local')
        self._partner('CLI-0412 Acquéreur de matériel', is_company=True, customer_rank=1)
        self.agent = self._partner('Agent collecte (EMP-0142)', ka_salarie=True, ka_matricule='EMP-0142')
        categ = self.env.ref('kode_agri_achats.categ_intrants')
        for code, nom, ptype in (('INT-CHM-0042', 'Coagulant acide formique', 'consu'), ('INT-FILM', 'Film polyéthylène emballage', 'consu'),
                                 ('P-0231', 'Roulement 9120', 'consu'), ('P-0244', 'Courroie transporteur', 'consu'), ('P-0250', 'Filtre', 'consu')):
            self._product(code, nom, type='consu', is_storable=True, categ_id=categ.id, standard_price=1000 if code.startswith('P') else 765)
        self._product('SRV-POSE', 'Pose et réglage séchoir', type='service', standard_price=150000)
        return '%d planteurs, clients, fournisseurs et articles' % (len(self.planteurs) + 1)

    # ---- M1 ---------------------------------------------------------------------------------------------------------------
    def _m1_parametres(self):
        today = date.today()
        fdt = self._ref('kode_agri_planteur.product_fdt_hevea')
        for decal in (1, 0):
            deb = (today.replace(day=1) - relativedelta(months=decal))
            fin = deb + relativedelta(months=1) - timedelta(days=1)
            if not self.env['ka.tarif'].search([('date_start', '=', deb)], limit=1):
                self.env['ka.tarif'].create({'product_id': fdt.id, 'date_start': deb, 'date_end': fin, 'bareme_ids': [
                    Command.create({'name': "Barème usine — pont de l'usine", 'lieu': 'usine', 'prix_kg': 615}),
                    Command.create({'name': 'Barème bord champ — ponts de proximité', 'lieu': 'bord_champ', 'prix_kg': 590})]})
        if not self.env['ka.prime.type'].search([], limit=1):
            self.env['ka.prime.type'].create([
                {'name': 'PRIME-KG', 'libelle': 'Prime au kilogramme', 'type_prime': 'kg', 'base_calcul': 'kg_achete', 'bareme': 5},
                {'name': 'PRIME-FID', 'libelle': 'Prime de fidélité', 'type_prime': 'fidelite', 'base_calcul': 'cumul', 'bareme': 3}])
        planteur = self.planteurs[0]
        if not self.env['ka.avance'].search([('partner_id', '=', planteur.id)], limit=1):
            av = self.env['ka.avance'].create({'partner_id': planteur.id, 'nature': 'numeraire', 'amount': 1_500_000,
                                               'regle_id': self._ref('kode_agri_planteur.regle_taux30').id})
            av.action_soumettre()
            av.action_approuver()
            av.action_verser()
        return 'barèmes Apromac, 2 primes, 1 avance versée'

    def _m1_flux(self):
        today = date.today()
        if self.env['ka.ticket.import'].search([('source', '=', 'DEMO')], limit=1):
            return 'déjà chargé'
        lignes = ['CodeFournisseur;N_Ticket;DatePesee;Article;Poids N;Site;N_Lot;EUDR']
        tickets = [(self.planteurs[0], 'T-D001', 1, 18240, 'LOT-D01'), (self.planteurs[1], 'T-D002', 1, 22500, 'LOT-D01'),
                   (self.coop, 'T-D003', 2, 41800, 'LOT-D02'), (self.planteurs[2], 'T-D004', 3, 19760, 'LOT-D03'), (self.planteurs[0], 'T-D005', 3, 25100, 'LOT-D04')]
        for p, num, jour, poids, lot in tickets:
            d = today.replace(day=min(jour, today.day))
            lignes.append('%s;%s;%s;FDT-HEVEA;%d;U01;%s;PARC-1' % (p.ka_code, num, d.strftime('%d/%m/%Y'), poids, lot))
        imp = self.env['ka.ticket.import'].create({'source': 'DEMO', 'filename': 'pesees_demo.csv',
                                                   'file': base64.b64encode('\n'.join(lignes).encode())})
        imp.action_importer()
        imp.action_verifier()
        imp.action_valider()
        gen = self.env['ka.generation'].create({'date_debut': today.replace(day=1), 'date_fin': today, 'date_comptable': today})
        gen.action_simuler()
        gen.action_lancer()
        factures = imp.ticket_ids.purchase_id.invoice_ids.filtered(lambda m: m.state == 'draft')
        factures.action_post()
        return '%d tickets → %d commande(s) → réceptions validées et factures' % (len(tickets), len(imp.ticket_ids.purchase_id))
