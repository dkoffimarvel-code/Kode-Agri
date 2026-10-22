# Kode Agri — ERP Odoo (caoutchouc naturel)

Addons Odoo 19 implémentant le cahier des charges *Kode Agri Odoo v4.5* (onze modules), avec les écrans reproduits
à l'identique des maquettes du cahier. Depuis la v4.2, les maquettes sont dessinées dans l'interface native d'Odoo :
barre d'application violette et ses menus, fil d'Ariane, boutons d'action et barre d'état dans l'en-tête, cartes KPI
à droite du titre, champs sur deux colonnes, onglets, bandeau bleu « ℹ » et encadré jaune « Validation / Approbation ».
Les règles de réalisation des écrans sont décrites dans [`docs/GUIDE_ECRANS.md`](docs/GUIDE_ECRANS.md).

| Addon | Application(s) | Contenu |
|---|---|---|
| `kode_agri_base` | — | Habillage (CSS, libellé « ERP KODE »), devise XOF « FCFA », mixin `ka.document` |
| `kode_agri_planteur` | Collecte FDT | **Module 1** : fiche planteur/coopérative et parcelles EUDR, prix Apromac, primes, avances (circuit de signature), import des tickets de pesée → commandes d'achat, génération des réceptions et factures (RG-1.7), virement multiple, chèque de règlement |
| `kode_agri_achats` | Achats, Inventaire | **Module 2** : données de base (articles, catégories, fournisseurs, entrepôts, structure), demande d'achat → appel d'offres → commande, réception partielle, facture et pièces obligatoires (RG-2.2), transferts, inventaire, dossiers d'import et frais d'approche |
| `kode_agri_immo` | Immobilisations | **Module 3** : catégories, fiche (manuelle ou depuis une facture), plan d'amortissement, dotations comptabilisées par section analytique, cessions et mises au rebut, parc |
| `kode_agri_production` | Fabrication, Qualité | **Module 4** : nomenclature et gamme TSR, OF de mélange / production / essai, paniers et colis (36 balles × 35 kg), DRC porté par le lot, spécification laboratoire (7 tests) et reclassement, reconditionnements, contrôles qualité, libération par équivalent conteneur |
| `kode_agri_vente` | Ventes | **Module 5** : client, contrats Spot / Long terme, sous-contrats, ordre de transit, jalons, voyage, empotage, bon d'expédition, déclaration d'exportation (DUS, parafiscalité), transfert au port, départ du navire |
| `kode_agri_frais` | Notes de frais | **Module 6** : saisie avec plafonds et justificatifs, approbation, comptabilisation ventilée, remboursement |
| `kode_agri_rh` | Employés, Présences, Congés, Paie, Missions, Recrutement, Formation | **Module 7** : dossier du personnel et contrat, feuilles de pointage (borne, PIN, API de pointeuse externe, anomalies RG-7.1), absences, congés et permissions (RG-7.2, RG-7.3), soldes et acquisition mensuelle, paie ivoirienne paramétrable (CNPS, ITS au barème progressif avec RICF, FDFP ; rubriques historisées RG-7.4) et écritures de paie analytiques, ordres de mission avec avance, per diem et régularisation (RG-7.5), demandes de personnel et candidatures (RG-7.6, RG-7.7), formations et compétences (RG-7.8), entretiens de carrière (RG-7.9) |
| `kode_agri_compta` | Comptabilité | **Module 8** : facture export en devise, rapprochement commande / réception / facture (RG-8.1), lettrage, planning de trésorerie, régularisations avec extourne (RG-8.5), schémas d'écritures |
| `kode_agri_gestion` | Contrôle de gestion | **Module 9** : cascade analytique par activité, unités d'œuvre et clés, budgets à deux couches, CAPEX, écarts, KPI, compte de résultat de gestion, trésorerie glissante |
| `kode_agri_maintenance` | Maintenance | **Module 10** : parc d'équipements hiérarchisé (site → atelier → ligne → machine → sous-ensemble) relié au poste de charge et à l'immobilisation, relevés de compteur, plans préventifs calendaires ou sur compteur (RG-10.1), demandes d'intervention, ordres de travail (main-d'œuvre, pièces sorties du magasin, demande d'achat si pièce indisponible RG-10.2), contrats de maintenance et sous-traitance avec réception à la clôture (RG-10.3), MTBF / MTTR / disponibilité, coût imputé au coût d'usinage |
| `kode_agri_flotte` | Parc automobile | **Module 11** : véhicules et engins, documents réglementaires avec alertes et blocage, entretien au kilométrage (RG-11.1), prestations externes de la commande à la facture (RG-11.2, RG-11.3), carburant (consommation, dérives, import des relevés de cartes, écriture analytique), affectations conducteur / véhicule (RG-11.4, RG-11.5) et ordre de mission vers la paie (RG-11.6), coût de revient kilométrique |
| `kode_agri_demo` | — | Données de démonstration chargées par les vrais flux (rapport étape par étape) et tests automatisés |

Les modules 7, 10 et 11 sont des modules spécifiques Kode Agri : ils n'exigent pas les applications Enterprise
(Paie, Évaluations…) ni les applications Maintenance / Flotte d'Odoo, et s'installent sur l'édition Community.

## Installation et contrôle

**Procédure complète avec données de démonstration : [`docs/INSTALLATION.md`](docs/INSTALLATION.md)** (`./scripts/install.sh`),
parcours écran par écran : [`docs/PARCOURS_DEMO.md`](docs/PARCOURS_DEMO.md), tests : `./scripts/run_tests.sh`.

Ordre d'installation (dépendances) : `kode_agri_base` → `kode_agri_planteur` → `kode_agri_production` → `kode_agri_achats`
→ `kode_agri_vente` → `kode_agri_frais` → `kode_agri_compta` → `kode_agri_gestion` → `kode_agri_immo` → `kode_agri_rh`
→ `kode_agri_maintenance` → `kode_agri_flotte` → `kode_agri_demo`.
Installer `kode_agri_flotte` suffit pour tout installer sans la démonstration ; `kode_agri_demo` installe tout et charge la démonstration.

Avant toute installation, `python3 tools/check_addons.py` vérifie sans Odoo les manifestes, les champs et boutons des vues,
les identifiants externes, les `env.ref()`, les définitions de champs et les pièges d'Odoo 17-19 (`tree`, `attrs`,
`decoration_…`, One2many affiché deux fois, ancienne mise en page). Il ne remplace pas un test sur une instance réelle.

## Limites connues

- Vérifié sur Odoo 19.0 Community (sources officielles, PostgreSQL 16, plan comptable `l10n_ci`) : installation complète,
  mise à niveau depuis la version précédente, démonstration (14 étapes « OK »), 22 tests automatisés, et ouverture dans le
  navigateur des 161 actions Kode Agri sans erreur. Une instance différente (Enterprise, autres modules installés) peut
  encore révéler des écarts.
- Paie : les taux CNPS, le barème ITS et la réduction pour charges de famille sont des **paramètres** (tables datées) chargés avec
  des valeurs indicatives ; ils doivent être validés par le service paie avant usage. Les déclarations CNPS / ITS sont des
  états d'analyse, pas les formulaires officiels.
- Rapports d'impression (bulletin, ordre de mission, certificats, bordereaux…) : les boutons affichent une notification ou
  s'appuient sur les vues d'analyse.
- Règles d'approbation hiérarchiques : les circuits sont des étapes à boutons, sans contrôle de droits par rôle.
- Paramétrage standard à réaliser dans Odoo : plan SYSCOHADA, taxes et positions fiscales, journaux (dont PAIE), rapprochement bancaire.
- Abonnement des charges et charges à répartir (§ 8.7.3-8.7.4) : non couverts (fonctions de report d'Odoo Enterprise).
- Applications natives homonymes : si les applications Achats, Inventaire, Ventes d'Odoo sont installées, leurs menus restent
  visibles à côté des applications Kode Agri de même nom.
