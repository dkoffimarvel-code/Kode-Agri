# Kode Agri — ERP Odoo (caoutchouc naturel)

Addons Odoo 17 implémentant le cahier des charges *Kode Agri Odoo v4.0*, avec les écrans reproduits
à l'identique des maquettes (barre noire « Kode Agri », fil d'Ariane, titre + pastille de statut, KPI,
bandeau d'information, sections, panneau **ACTIONS / LIENS** à droite).

| Addon | Contenu |
|---|---|
| `kode_agri_base` | Habillage (CSS + barre de navigation), devise XOF « FCFA », mixin `ka.document` |
| `kode_agri_planteur` | **Module 1** : fiche planteur/coop + parcelles EUDR, tarifs Apromac, primes, avances (circuit de signature), import tickets de pesée → commandes d'achat, génération réceptions/factures (RG-1.7), proposition de virement multiple, règlement par chèque |

Installation : ajouter `addons/` à l'`addons_path`, puis installer `kode_agri_planteur`
(dépend de contacts, purchase, stock, account). Édition Community suffisante pour le module 1.

Modules 2 à 8 : à venir (même patron de vues).
