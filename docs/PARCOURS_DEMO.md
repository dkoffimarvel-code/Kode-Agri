# Parcours de démonstration — écran par écran

Connexion : <http://localhost:8069>, base `kode_demo`, `admin` / `admin`. Les chiffres ci-dessous sont ceux que la
démonstration produit ; quand ils diffèrent des maquettes du cahier des charges, l'écart est expliqué.

## Module 1 — Planteurs et coopératives  (application : *Collecte FDT*)

| Écran | À voir | Valeurs attendues |
|---|---|---|
| Planteurs | 3 planteurs (`PLT-…`) + la coopérative (`COOP-…`), parcelles EUDR | solde d'avance du 1er planteur : **1 500 000** |
| Avances | avance versée, circuit de signature (3 étapes faites) | règle « Taux fixe 30 % » |
| Prix Apromac | prix Apromac du mois | usine **615**, bord champ **590** FCFA/kg |
| Tickets | lot d'import `DEMO`, 5 tickets validés, 5 commandes générées | 127 400 kg ; total commandes **78 351 000** |
| Décomptes › Génération réceptions et factures | tâche terminée, trace | 5 commandes, 5 factures |
| *À faire à la main* | Comptabilité › Paiements › Virement multiple : saisir une plage de dates, vérifier la liste des nets à payer, **Approuver** puis **Générer les règlements** | |

## Module 4 — Production et qualité  (applications : *Fabrication*, *Qualité*)

| Écran | À voir | Valeurs attendues |
|---|---|---|
| Nomenclatures | TSR, gamme `GAM-TSR-01` (8 opérations), cadence calculée | postes de charge U01 (21) |
| OF de mélange | 4 lots de FDT alloués, DRC 60 %, FDT consommé | mélange `MEL-…` |
| OF de production | statut Produit ; mélange affecté ; **TSR estimé 76 440 kg** (RG-4.8) | 61 colis estimés / 16 déclarés |
| Déclaration des paniers | 8 paniers validés de 72 balles | contrôle P0/PRI 32 / 54 sur le 1er |
| Suivi de production | 16 colis de 1 260 kg (36 balles) ; le 16ᵉ en points blancs | |
| Qualité › Résultats d'analyse | 7 tests, grade **TSR10** déterminé, article créé | seuils TSR10 du cahier |
| Reconditionnement | *à faire* : créer un ordre « spécifications » pour un colis TSR10 et saisir les nouveaux résultats **P0 32, PRI 45, impuretés 0,15, VM 0,95, azote 0,80, cendres 1,1** → grade **TSR20** (la grille du cahier l'exige) ; P0 28 donnerait OFFSPECS | OF de reclassement 1 pour 1, anciens résultats historisés |
| Libération conteneur | 15 colis libérés (statut A) ; *à essayer* : créer un contrôle contenant le colis points blancs → ligne **Bloqué — à remplacer**, et « Valider le conteneur » refusé (RG-4.12) | |

## Module 5 — Vente et logistique export  (application : *Ventes*)

| Écran | À voir | Valeurs attendues |
|---|---|---|
| Clients | TyreCorp Ltd, spécifications 7 tests, documents requis | |
| Commandes ouvertes | contrat Long terme CV-0061 *signé* | 1 008 000 kg → **50 conteneurs, 28 800 balles** ; **1 159 200 EUR = 760 385 354 FCFA** ✔ maquette |
| Commandes de vente (Spot) | contrat Spot *à signer* ; spécifications modifiables | |
| Sous-contrats | booking `BKG-0061-03`, BMC requis (MAERSK), limite de booking | 40 320 kg = **2 conteneurs, 1 152 balles** ✔ ; 46 368 EUR |
| Ordres de voyage | 2 conteneurs affectés, article conteneur créé en stock au coût 0, limite de détention (prise + 13 j) | |
| Empotage | **15 colis** alloués (capacité 16) ; le colis points blancs est exclu (RG-5.15) | |
| Livraisons | bon validé → conteneur *Empoté*, colis transférés au terre-plein | |
| Déclarations d'exportation | DUS : TCT 0,1 % du CAF, TS douane 20 000, agios 0,2 %, gestion crédit 0,4 % ; parafiscalité 22 FCFA/kg | DUS **59 540** ; parafiscalité **887 040** |
| *À faire à la main* | Transferts port → Départ navire → Générer la facture ; essayer de clôturer sans cocher la liasse (RG-5.14) | |

## Module 6 — Notes de frais  (application : *Notes de frais*)

Note « Tournée collecte Sud » : 3 dépenses, **96 500 FCFA** ✔ maquette, comptabilisée (journal NDF, compte 421000).
*À faire* : *Proposer au règlement* puis *Régler le salarié* (nécessite un journal de banque).
Test de plafond : créer une nouvelle note avec 60 000 sur une ligne carburant, puis soumettre → refus (plafond 50 000).

## Module 2 — Achats et stock  (applications : *Achats*, *Inventaire*)

| Écran | À voir | Valeurs attendues |
|---|---|---|
| Articles, Catégories article | `INT-CHM-0042`, catégorie INTRANTS, comptes hérités 3211 / 6021 / 6031 | |
| Demandes d'achat | DA signée et soldée | 2 lignes |
| Réponses fournisseurs | 3 offres, mieux-disant retenu | **480 000 / 484 000 / 538 000** (maquette : 480 000 / 496 000 / 538 000) |
| Commandes d'achat | commande signée → réception générée | 480 000 |
| Réceptions | réception **partielle** : courroies 4/6, reliquat 2 | |
| Factures fournisseurs | 3 pièces obligatoires fournies, facture validée | |
| Dossiers d'import | `IMP-…`, 3 articles, frais 1 871 250 ventilés par valeur FOB | **1 145 205 / 404 190 / 321 855** ; coût complet **16 871 250** (maquette : 1 145 250 / 404 250 / 321 750, total identique) |
| Transferts, Inventaires | un transfert, un inventaire en comptage (écart −1 sur les courroies) | |

## Module 3 — Immobilisations  (menu : *Immobilisations*)

| Écran | À voir | Valeurs attendues |
|---|---|---|
| Familles | EQTRANS (10 ans, 2154 / 28154 / 68112), MATTRANS, BATIND | |
| Immobilisations | séchoirs et presse en service ; plan mensuel | séchoir ligne 2 : **333 333 / mois** |
| Comptabilisation des dotations | traitement du mois précédent, **comptabilisé** | **1 233 333** FCFA ✔ maquette, 3 pièces ventilées L2/L3-SECHAGE et L2-PRESSAGE |
| Cessions et mises au rebut | Laminoir 1, prix 4 500 000, VNC et plus-value calculées *(à valider)* | VNC dépend de la date du jour |
| Consultation du parc | indicateurs, regroupement par famille | |

## Module 7 — Ressources humaines et paie  (applications : *Employés*, *Présences*, *Congés*, *Paie*, *Missions*, *Recrutement*, *Formation*)

| Écran | À voir | Valeurs attendues |
|---|---|---|
| 7.1 Employés | `EMP-0211 — Opérateur séchage`, CDI, Atelier / Ligne 2 ; onglet Contrat : éléments de rémunération | salaire de base **185 000**, prime de poste **25 000**, indemnité transport **15 000** |
| 7.2.1 Présences › Feuilles de pointage | semaine précédente : pointages reçus par l'API (mode « Import API » ou « Badge »), jeudi **Anomalie : pointage manquant**, encadré « 1 anomalie à régulariser » ; *Valider* est refusé (RG-7.1) | heures théoriques 40h00 ; mercredi **+2h13 (heures sup.)** |
| Présences › Présences | événements de pointeuse rapprochés / en anomalie / rejetés | |
| 7.2.4 Congés › Mes congés | demande de congé annuel *À approuver*, tableau des soldes | acquis **26,4**, pris **11,9**, solde **14,5** ; solde après validation **9,5** |
| 7.2.5 Congés › Demandes › Demandes d'absence | absence maladie approuvée (2 niveaux), barème d'ancienneté avec « Cas du collaborateur » | maintien : 1 mois plein puis 2 mois à demi-salaire |
| 7.3 Paie › Bulletins | bulletin du mois précédent *Confirmé* et comptabilisé ; bulletins du mois *Calculés* | salaire de base 185 000, cotisations sociales −6,3 %, net à payer ; écriture 661 / 664 / 431 / 447 / 422 |
| Paie › Configuration | rubriques datées (RG-7.4), barème ITS 2024, RICF | *valeurs indicatives à valider par le service paie* |
| 7.4 Missions › Ordres de mission | `OM-…` « Tournée collecte Sud » *À régulariser* : avance 175 000 versée, per diem 35 000 × 5 jours, frais réels de la note de frais | régularisation **+96 500 FCFA (complément à verser)** ; un second ordre *À approuver* |
| 7.5.1 Recrutement › Demandes de personnel | DP « Opérateur séchage » approuvée puis poste ouvert ; DP de création de poste *À valider* (la direction valide toujours, RG-7.6) | |
| 7.5.2 Recrutement › Candidatures | Awa Koffi `CAND-…` en *Entretien*, grille 4/5 · 5/5 · 5/5 | |
| 7.6.2 Formation › Sessions | « Habilitation électrique BR » *En cours*, 3 / 6 places occupées, participants Validé / En attente / Validé ; *Clôturer la session* met à jour la compétence (RG-7.8) | coût 450 000, FDFP taxe d'apprentissage |
| 7.6.3 Formation › Entretiens | entretien annuel *Entretien manager*, compétences Progression / Nouvelle compétence ; *Finaliser* programme le suivant (RG-7.9) | |

## Module 8 — Comptabilité et finance  (application : *Comptabilité*)

| Écran | À voir | Valeurs attendues |
|---|---|---|
| Factures de vente — export | facture provisoire TyreCorp en USD, cours 610 | 20,16 t × 1 250 = **25 200 USD** ✔ maquette |
| Contrôle facture à trois niveaux | facture fournisseur rapprochée ; modifier une quantité facturée pour provoquer un écart → refus de validation | tolérance prix 2 % |
| Lettrage automatique | écritures du planteur ; *Lettrer automatiquement* | |
| Prévisions de trésorerie | 6 rubriques, vue mensuelle ↔ hebdomadaire | alimentées par les factures ouvertes et 4 prévisions manuelles |
| Régularisations | CCA de 1 200 000 en brouillon : *Comptabiliser*, puis *Extourner* (au lendemain de la clôture) | |
| Schémas d'écritures | 35 lignes issues des 13 grilles du cahier, groupées par domaine | |

## Module 9 — Contrôle de gestion  (application : *Contrôle de gestion*)

| Écran | À voir | Valeurs attendues |
|---|---|---|
| Balance analytique | axe croisé *Grade = TSR10* | cascade **28 400 000 / 9 200 000 / 2 600 000 / 900 000 / 1 000 000** ; coût complet **42,1 M**, part du FDT **67 %** ✔ maquette |
| Clés par unités d'œuvre | VH0001, mois précédent : clés calculées | **45 / 30 / 25 %** ; répartition 4,20 → 1,89 / 1,26 / 1,05 ✔ ; cliquer *Lancer la répartition* |
| Saisie des budgets | budget de l'année **validé — verrouillé** (essayer de modifier : refus) ; *Créer une révision* | maquette générée depuis le réalisé N-1 |
| Consultation des budgets / Suivi par activité | choisir une ligne et un mois : détail des écritures | |
| Budget / réalisé | écarts par section, notes d'analyse, seuil 2 % | |
| Budgets d'investissement | bon de **185 M FCFA** autorisé (circuit jusqu'au CA) ; *Consulter les engagements* | |
| Pilotage industriel et financier | 6 KPI, marge par grade, coût standard / réel | dépend des colis et écritures du mois |
| Compte de résultat de gestion | mois, cumul, % CA, N-1 | |
| Trésorerie glissante | 6 colonnes, alerte sous le seuil de 150 M FCFA | |

## Module 10 — Maintenance des engins et des machines  (application : *Maintenance*)

| Écran | À voir | Valeurs attendues |
|---|---|---|
| 10.1 Équipements | `EQ-SECH-02 — Séchoir n°2`, poste de charge Séchoir 2, immobilisation « Séchoir ligne 2 », sous-ensembles Brûleur 1 et Brûleur biomasse ; onglet Fiabilité | compteur **12 480 h**, criticité **Critique** |
| 10.3 Préventif | plan « Graissage paliers » toutes les 500 h : le relevé de 12 480 h a franchi le seuil d'anticipation → **OT préventif généré automatiquement** (RG-10.1) ; révision trimestrielle, contrôle réglementaire annuel | prochaine échéance **12 500 h (proche)** |
| 10.2 Ordres de travail | OT correctif « brûleur 1 défaillant » *En cours* : main-d'œuvre 3,7 h, injecteurs ×2, joints ×4 ; *Demander pièce* crée une demande d'achat si le stock manque (RG-10.2) | coût de l'OT **262 000 FCFA** |
| 10.5 Demandes de maintenance | « Allumage instable — brûleur biomasse » *En qualification*, équipement à l'arrêt total ; *Convertir en ordre de travail* / *Traiter en urgence* | |
| 10.6 Contrats & prestataires | 5 contrats : AfricTherm *À renouveler* (activité « renégocier l'échéance »), Atlas *Expiré* ; OT externalisé : demande d'achat → commande signée → clôture = réception automatique (RG-10.3) | 45 000 F CFA / h |
| États | plan de charge, carnet de santé, coûts, tableau de bord fiabilité (MTBF, MTTR, disponibilité), pièces critiques, suivi des factures | |

## Module 11 — Gestion du parc automobile  (application : *Parc automobile*)

| Écran | À voir | Valeurs attendues |
|---|---|---|
| 11.1 Véhicules | `AA-123-BC — Camion collecte`, Renault Kerax, 15 t, conducteur Traoré Issa, immobilisation ; documents : visite technique **Échéance proche** ; le 4×4 AA-456-CD a une visite échue → bloqué à l'affectation (§ 11.4) | compteur **148 405 km** après la tournée du jour |
| 11.2 Entretien | ordre `ENT-…` « Révision des 150 000 km » **généré au kilométrage** (seuil d'anticipation 148 000 km franchi par le plein, RG-11.1), *En cours* à l'atelier interne ; entretien externe du 4×4 : demande d'achat validée → appel d'offre (RG-11.2) | coût **743 000 FCFA** |
| 11.3 Carburant | 4 pleins, consommation et dérives, écriture 602200 / 4081 ventilée par activité, véhicule et zone ; *Importer un relevé de cartes* pour les rapprocher | conso **12,4 L/100 km** au dernier plein |
| 11.5 Affectations | `AFF-…` du jour *Terminée* : 85 km, 06:05 → 12:20 ; **ordre de mission généré** et transmis à la paie (RG-11.6) ; une deuxième affectation simultanée du camion est refusée (RG-11.5) | durée réelle **6 h 15** |
| États | OT en attente de facture, consommation et dérives, échéancier des documents, coût de revient kilométrique, planning, ordres de mission | |

## Différences connues avec les maquettes

- Les écrans sont des formulaires Odoo natifs reprenant les **libellés, la disposition et les règles** des maquettes v4.5 ;
  les écarts propres à chaque écran sont décrits dans `docs/GUIDE_ECRANS.md` et dans l'historique des modifications.
- Les maquettes contiennent quelques incohérences internes (nombre de conteneurs d'un contrat, clés de répartition,
  sens de l'écart budgétaire) : voir `README.md` et les comptes rendus de chaque module.
- Les impressions (contrat, ordre de transit, certificats, bordereaux) affichent une notification : les rapports
  d'impression ne sont pas encore écrits.
