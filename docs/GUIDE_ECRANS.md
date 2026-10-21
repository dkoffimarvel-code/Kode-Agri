# Guide de réalisation des écrans Kode Agri (cahier des charges v4.5)

Depuis la v4.2 du cahier des charges, les maquettes sont dessinées **dans l'interface native d'Odoo**.
Chaque écran Kode Agri est donc un formulaire Odoo standard, enrichi de quelques classes CSS
(`kode_agri_base/static/src/css/kode_agri.css`). L'écran de référence est la fiche planteur
(`kode_agri_planteur/views/partner_views.xml`, vue `view_ka_planteur_form`, écran 1.1).

## Correspondance maquette → vue Odoo

| Élément de la maquette | Réalisation |
|---|---|
| Barre violette « Collecte FDT · Planteurs · Avances… » | Menu racine d'application (`menuitem` sans parent) nommé comme l'application de la maquette, sous-menus = entrées de la barre |
| « ERP KODE » en haut à droite | Élément de la barre système fourni par `kode_agri_base` |
| Fil d'Ariane « Planteurs / PLT-1087 — Kouassi N'Guessan » | Natif : nom de l'action (`Planteurs`) puis `display_name` de l'enregistrement (`_compute_display_name` sur les modèles `ka.*`) |
| Boutons « Nouveau · Enregistrer · Octroyer avance… » | `<header>` : boutons `type="object"` ; le bouton plein de la maquette porte `class="btn-primary"`, les boutons à contour `class="btn-secondary"` ; « Enregistrer » = `special="save"` ; « Nouveau » = méthode `action_creer` (mixin `ka.document`) |
| Étapes « Brouillon › Actif › Archivé » à droite | `<field name="state" widget="statusbar" statusbar_visible="…"/>` dans le `<header>` |
| Cartes « 57 Livraisons », « 670 k Solde avance » | `<div class="oe_button_box">` + `<button class="oe_stat_button" type="object" name="…">` avec `o_stat_value` / `o_stat_text` (sans icône) |
| Titre et sous-titre gris | `<div class="oe_title"><h1>…</h1><div class="o_ka_sub">…</div></div>` |
| Bandeau bleu « ℹ … » | `<div class="o_ka_info">texte</div>` (titre en gras : `<span class="o_ka_info_t">…</span>`, sans icône : classe `o_ka_noicon`) |
| Champs libellé / valeur sur deux colonnes | `<group><group>…</group><group>…</group></group>`, libellés de la maquette en `string`, astérisque = `required` |
| Pastille (« Planteur & coopératives », « Critique ») | `widget="badge"` avec `decoration-*` |
| Onglets | `<notebook><page string="…">` dans l'ordre de la maquette |
| Tableau avec ligne de total violette | Liste intégrée (`<list>` avec `sum`) ou tableau HTML calculé `table.o_ka_tbl` (`tfoot` ou `tr.o_ka_total`) |
| Encadré jaune « Validation / Approbation » | `<div class="o_ka_valid"><span class="o_ka_valid_t">Validation / Approbation</span>texte</div>` |
| Fil de discussion (maintenance, contrats) | `<chatter/>` sur les modèles `mail.thread` |

## Règles Odoo 19

* Vues `<list>` (jamais `tree`), `view_mode` « list,form » ; pas d'attributs `attrs` / `states`
  (utiliser `invisible="state != 'x'"`, `readonly="…"`).
* Pas de `env`, `search`, `browse` ni `self` dans les `eval` des fichiers de données.
* Identifiants externes d'un autre module toujours préfixés (`kode_agri_achats.menu_…`).
* Un champ `related` a exactement le type du champ cible (Monetary ≠ Float).
* `activity_schedule` uniquement sur les modèles qui héritent de `mail.activity.mixin`.

## Contrôle

`python3 tools/check_addons.py` vérifie aussi que l'ancienne mise en page (panneau Actions/Liens, fil d'Ariane
« Fonction : … ») a disparu, que les cartes KPI ont une action, et l'absence de `tree` / `attrs` / `states`.
