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

Modules 2, 3, 7 et 8 : à venir (même patron de vues).

**Non testé sur une instance Odoo** : la syntaxe Python/XML et la cohérence champs ↔ vues sont vérifiées
statiquement, mais le chargement réel dans Odoo 19 reste à valider.
