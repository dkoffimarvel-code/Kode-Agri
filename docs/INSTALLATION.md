# Installation et premier test — Kode Agri sur Odoo 19

Les dix addons de ce dépôt n'ont **jamais été chargés dans une instance Odoo** : ils ont été écrits et vérifiés
statiquement. Cette procédure sert à les installer, à les parcourir avec des données de démonstration et à relever
les erreurs d'une première exécution. C'est normal d'en trouver : voir la section « Si quelque chose échoue ».

## 1. Prérequis

| Élément | Version / remarque |
|---|---|
| Docker + Docker Compose v2 | pour la voie rapide (recommandée) |
| Odoo | **19.0 Community suffit** ; aucun addon n'exige l'édition Enterprise |
| PostgreSQL | 16 (fourni par `docker-compose.yml`) |
| Mémoire | 4 Go minimum pour l'installation |

La voie sans Docker est décrite au § 4.

## 2. Voie rapide (Docker)

```bash
git clone <ce dépôt> && cd Kode-Agri-Caoutchouc
git checkout claude/magical-edison-sq6gjn
./scripts/install.sh              # base « kode_demo » ; compter 5 à 15 minutes
```

Le script enchaîne six étapes et s'arrête à la première erreur système :

1. **Base de données** : initialise `kode_demo` avec le module `base`.
2. **Société en Côte d'Ivoire, devise XOF**, *avant* toute écriture comptable (la devise d'une société ne se change plus
   ensuite) ; mot de passe `admin` pour l'utilisateur administrateur.
3. **Plan comptable SYSCOHADA** : `l10n_ci`, sinon repli sur `l10n_syscohada`.
4. **Addons Kode Agri + démonstration** : installe `kode_agri_demo`, qui tire les douze autres addons.
5. **Rapport de démonstration** : une ligne `OK` ou `ÉCHEC` par étape (voir § 3).
6. **Démarrage** d'Odoo sur <http://localhost:8069> (identifiant `admin`, mot de passe `admin`).

Ordre d'installation des addons (résolu automatiquement par les dépendances) :
`kode_agri_base` → `planteur` → `production` → `achats` → `vente` → `frais` → `compta` → `gestion` → `immo` → `rh`
→ `maintenance` → `flotte` → `demo`.

## 3. Lire le rapport de démonstration

Le chargement passe par les **vrais traitements** des modules (import des tickets de pesée, génération des commandes,
déclaration des colis, signature des contrats…). Chaque étape est isolée : si l'une échoue, les suivantes continuent.

```
OK    Contexte (société, devises, comptes, journaux) — 31 compte(s) créé(s)
OK    M1 — Tarifs, primes, avances — barèmes Apromac, 2 primes, 1 avance versée
ÉCHEC M4 — Mélange, production, … — UserError: …
```

- Une ligne `ÉCHEC` désigne **un flux réellement cassé** ; le détail (trace complète) est dans le journal
  `/tmp/kode_install_kode_demo.log` (chercher « Démo Kode Agri »).
- Relire le rapport à tout moment :
  `docker compose run --rm -T odoo odoo shell -c /etc/odoo/odoo.conf -d kode_demo --no-http <<< "print(env['ir.config_parameter'].sudo().get_param('kode_agri.demo_rapport'))"`
- Après une correction du code, relancer le chargement (les étapes déjà faites sont sautées) :
  `... odoo shell ... <<< "print(env['ka.demo'].charger()); env.cr.commit()"`

Ce que la démonstration crée (cohérent avec les maquettes du cahier des charges) :
5 tickets de pesée (127 400 kg) → 5 commandes → réceptions par lot → factures ; 1 mélange, 1 OF de production,
8 paniers, **16 colis** (15 libérés TSR10, 1 en points blancs) ; 1 contrat Long terme signé, 1 Spot, 1 sous-contrat booké,
1 voyage, 1 conteneur empoté ; 1 note de frais comptabilisée ; 1 cycle d'achat complet et 1 dossier d'import ;
4 immobilisations et la dotation du mois (1 233 333 FCFA) ; 1 facture export en USD ; 1 budget validé + sa révision ;
1 bon CAPEX de 185 M FCFA autorisé ; la répartition du camion VH0001 ;
7 salariés, 2 feuilles de pointage (dont une en anomalie RG-7.1), des demandes de congé / d'absence / de permission,
un bulletin confirmé et comptabilisé puis les bulletins du mois, 2 ordres de mission, 1 demande de personnel et une
candidature en entretien, 1 session de formation en cours et 1 entretien de carrière ; 9 équipements dont le séchoir n°2
et ses sous-ensembles, 3 plans préventifs (un OT généré au compteur), 1 demande d'intervention, un OT correctif en cours,
un OT externalisé réceptionné, 5 contrats de maintenance ; 3 véhicules, documents réglementaires, 4 pleins, l'ordre
d'entretien des 150 000 km généré au kilométrage, 4 affectations et un ordre de mission transmis à la paie.

## 4. Mettre à jour une instance existante (envoi de fichiers ou zip)

1. Décompresser `kode_agri_addons.zip` : il contient les 13 dossiers `kode_agri_*`.
2. Dans le dossier des addons du serveur (par exemple `/mnt/extra-addons/`), **supprimer** les anciens dossiers `kode_agri_*`
   puis déposer les nouveaux (ne pas fusionner : d'anciens fichiers resteraient).
3. Redémarrer le service Odoo.
4. Mode développeur → Applications → « Mettre à jour la liste des applications ».
5. Ouvrir chaque module Kode Agri déjà installé et cliquer **Mettre à niveau** (l'habillage et les écrans ont changé) ;
   installer ensuite les nouveaux modules : `kode_agri_rh`, `kode_agri_maintenance`, `kode_agri_flotte` (ou `kode_agri_demo`,
   qui les tire tous et charge la démonstration).
6. Vider le cache du navigateur (Ctrl + F5) pour charger le nouveau CSS.

En cas d'erreur, copier le **texte complet** du message (bouton « Copier » de la fenêtre d'erreur) et le coller dans le
message, avec le nom du module en cours d'installation.

## 5. Sans Docker

1. Installer Odoo 19 selon la documentation officielle (paquet, source ou image) et PostgreSQL.
2. Ajouter le dossier `addons/` du dépôt à `addons_path` dans `odoo.conf`.
3. Créer une base **avec le pays Côte d'Ivoire** (devise XOF) *ou* appliquer l'étape 2 du script `install.sh`.
4. Installer le plan comptable : `-i l10n_ci` (ou `l10n_syscohada`).
5. Installer la démonstration : `odoo -d MABASE -i kode_agri_demo --stop-after-init`.
   Pour installer **sans** la démonstration, installer `kode_agri_flotte` à la place (il tire tous les autres addons).

## 6. Tests automatisés

```bash
./scripts/run_tests.sh            # base jetable « kode_test », ne touche pas à la démonstration
```

Trois familles de tests (étiquette `kode_agri`) :
- **Calculs purs** : plan d'amortissement, spécifications, formats des maquettes ;
- **Règles de gestion** : budget validé verrouillé, ventilation des frais d'import (somme = total) ;
- **Bout en bout** : échoue avec la liste des étapes de démonstration en `ÉCHEC`, et vérifie les chiffres clés
  (5 tickets, 16 colis, 15 libérés, dotation 1 233 333) ;
- **Modules 7, 10 et 11** (`test_v45.py`) : barème ITS, cascade du bulletin et RG-7.4, anomalies de pointage (RG-7.1),
  API de pointeuse, congé annuel (RG-7.2), plafond des permissions (RG-7.3), recrutement (RG-7.6, RG-7.7), compétences
  (RG-7.8), OT préventif au compteur (RG-10.1), OT externe sans commande approuvée (RG-10.3), consommation de carburant,
  affectation unique (RG-11.5), ordre de mission (RG-11.6), document échu bloquant.

Avant tout cela, sans instance Odoo : `python3 tools/check_addons.py` (manifestes, champs et boutons des vues, xmlid).

## 7. Si quelque chose échoue

| Symptôme | Cause probable | Action |
|---|---|---|
| `ParseError` / `ValueError: External ID not found` à l'installation | identifiant externe ou champ de vue inconnu d'Odoo 19 | relever le fichier et la ligne du message |
| `AttributeError: … has no attribute '_column_name'` ou erreur sur `account.analytic.line` | structure des plans analytiques différente en 19 | signaler : `kode_agri_gestion/models/common.py` isole cet accès |
| `Le compte XXXX est introuvable` | compte absent du plan comptable | normal hors démo : créer le compte ou adapter la famille / catégorie |
| Étape `Contexte` : « la devise de la société est EUR » | base créée sans le pays Côte d'Ivoire | refaire l'étape 2 sur une base vierge |
| Étape `M1 — Tickets…` : « You need to supply a Lot/Serial Number » | réception du fond de tasse (article suivi par lot) | signaler avec la trace complète |
| Un menu ou un écran n'apparaît pas / s'affiche nu | CSS non chargé | vider le cache navigateur, mode debug `?debug=assets` |

**À m'envoyer** pour corriger : (1) le rapport de démonstration complet, (2) les lignes `ERROR`/`Traceback` du journal
`/tmp/kode_install_kode_demo.log`, (3) la sortie de `./scripts/run_tests.sh`, (4) la version exacte d'Odoo
(`odoo --version`) et l'étiquette d'image utilisée. Les erreurs d'installation se corrigent une par une : chaque
correction fait avancer l'installation jusqu'à l'erreur suivante.

## 7. Repartir de zéro

```bash
docker compose down -v            # supprime la base et le dossier de données
./scripts/install.sh
```
