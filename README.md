# Kode Agri — ERP Odoo (caoutchouc naturel)

Addons Odoo 19 implémentant le cahier des charges *Kode Agri Odoo v4.0*, avec les écrans reproduits
à l'identique des maquettes (barre noire « Kode Agri », fil d'Ariane, titre + pastille de statut, KPI,
bandeau d'information, sections, panneau **ACTIONS / LIENS** à droite).

| Addon | Contenu |
|---|---|
| `kode_agri_base` | Habillage (CSS + contexte dans la barre de navigation), devise XOF « FCFA », mixin `ka.document` |
| `kode_agri_planteur` | **Module 1** : fiche planteur/coop + parcelles EUDR, tarifs Apromac, primes, avances (circuit de signature), import tickets de pesée → commandes d'achat, génération réceptions/factures (RG-1.7), proposition de virement multiple, règlement par chèque |

Installation : ajouter `addons/` à l'`addons_path`, puis installer `kode_agri_planteur`
(dépend de contacts, purchase, stock, account). Édition Community suffisante pour le module 1.

| `kode_agri_production` | **Module 4** : nomenclature/gamme TSR et 21 postes de charge U01, OF de mélange / production / essai (estimation du TSR RG-4.8, statut EUDR hérité), déclaration de paniers et de colis (36 balles × 35 kg), DRC porté par le lot avec historique, spécification laboratoire (7 tests, grades TSR10/TSR20/OFFSPECS) avec reclassement 1 pour 1, reconditionnement texture / spécifications, contrôles qualité (réception, essai DRC, granulés, panier P0/PRI, libération par équivalent conteneur) |

| `kode_agri_vente` | **Module 5** : fiche client (spécifications 7 tests, documents requis), contrats Spot / Long terme avec conversion kg → conteneurs/balles et héritage des spécifications (RG-5.3/5.5), sous-contrats (booking 48 h / 7 j, BMC), ordre de transit, jalons départ port, ordre de voyage (2 conteneurs max, détention par armateur), empotage avec filtre de conformité et capacité 16/17 colis, bon d'expédition, déclaration d'exportation (DUS, parafiscalité), transfert au port, départ navire et clôture documentaire |

| `kode_agri_frais` | **Module 6** : notes de frais (saisie par catégorie avec plafonds et justificatifs, approbation, pièce comptable NDF ventilée par section analytique avec contrepartie 421000, remboursement du salarié par virement lettré) |

| `kode_agri_achats` | **Module 2** : données de base (articles, catégories avec code comptable et section analytique « achats stockés », fournisseurs frais généraux, dépôts, structure), demande d'achat → appel d'offres → commande (génère la commande et la réception Odoo), réception partielle avec reliquat, facture et pièces obligatoires (RG-2.2), transfert intersites, inventaire valorisé, dossiers d'import avec ventilation des frais d'approche (valeur / poids / quantité) et coût complet d'entrée |

| `kode_agri_immo` | **Module 3** : familles d'immobilisations, fiche (manuelle ou issue d'une facture fournisseur à la validation), plan d'amortissement mensuel linéaire ou dégressif avec prorata, comptabilisation des dotations par pièce ventilée sur la section analytique, cessions et mises au rebut (VNC, plus ou moins-value), consultation du parc |

| `kode_agri_compta` | **Module 7** : facture de vente export en devise, contrôle à trois niveaux commande / réception / facture avec tolérances (RG-7.1), lettrage automatique, prévisions de trésorerie en six rubriques (vues mensuelle et hebdomadaire), régularisations d'arrêté CCA / PCA / CAP / PAR avec extourne automatique (RG-7.5) et provisions, schémas d'écritures du cahier en données de paramétrage |

| `kode_agri_gestion` | **Module 8** : cascade analytique par activité (axes croisés grade / campagne / site), unités d'œuvre et clés de répartition mensuelles, budgets à deux couches (détail et consolidé) avec génération de la maquette depuis le réalisé, import, validation verrouillée et révisions, drill-down, bons à budgétiser CAPEX avec circuit de signature, analyse des écarts avec alertes, KPI, compte de résultat de gestion, trésorerie glissante |

Les huit modules du cahier des charges sont couverts (voir les limites ci-dessous). (même patron de vues).

**Non testé sur une instance Odoo** : la syntaxe Python/XML et la cohérence champs ↔ vues sont vérifiées
statiquement, mais le chargement réel dans Odoo 19 reste à valider.


## Installation et contrôle

Ordre d'installation (dépendances) : `kode_agri_base` → `kode_agri_planteur` → `kode_agri_production` → `kode_agri_achats`
→ `kode_agri_vente` → `kode_agri_frais` → `kode_agri_compta` → `kode_agri_gestion` ; `kode_agri_immo` après `kode_agri_achats`.
Il suffit d'installer `kode_agri_gestion` et `kode_agri_immo` : leurs dépendances viennent avec.

Avant toute installation, `python3 tools/check_addons.py` vérifie sans Odoo les manifestes, les champs et boutons des vues,
les identifiants externes et les `env.ref()`. Il ne remplace pas un test sur une instance réelle.

## Limites connues

- Aucun addon n'a encore été chargé dans une instance Odoo 19 : le premier test d'installation révélera des erreurs que
  l'analyse statique ne voit pas (signatures d'API, comportements propres à la version 19).
- Rapports d'impression (certificats, bordereaux, ordre de transit, contrat…) : les boutons affichent une notification.
- Règles d'approbation hiérarchiques : les circuits sont des étapes à boutons, sans contrôle de droits par rôle.
- Paramétrage standard à réaliser dans Odoo : plan SYSCOHADA, taxes et positions fiscales, journaux de banque, rapprochement bancaire.
- Abonnement des charges et charges à répartir (§ 7.7.3-7.7.4) : non couverts (fonctions de report d'Odoo Enterprise).
