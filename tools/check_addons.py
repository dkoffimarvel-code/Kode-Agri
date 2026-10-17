#!/usr/bin/env python3
"""Contrôle statique des addons Kode Agri (sans instance Odoo).

Vérifie : manifestes (fichiers présents, dépendances, absence de cycle), champs cités dans les vues,
méthodes des boutons, identifiants externes (xmlid) des vues et des données, appels env.ref().
Ne remplace pas une installation réelle : à lancer avant, pour éliminer les erreurs évidentes.

    python3 tools/check_addons.py [dossier_addons]
"""
import ast
import glob
import os
import re
import sys

from lxml import etree

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'addons')
os.chdir(ROOT)
erreurs = []

CHAMPS = ('Char', 'Float', 'Integer', 'Boolean', 'Selection', 'Date', 'Datetime', 'Many2one', 'One2many', 'Many2many',
          'Monetary', 'Text', 'Binary', 'Html')
STD = {'id', 'name', 'display_name', 'state', 'create_uid', 'create_date', 'active', 'date', 'user_id', 'company_id', 'currency_id'}
ETENDUS = {'res.partner', 'stock.lot', 'mrp.bom', 'mrp.routing.workcenter', 'mrp.workcenter', 'ka.ticket', 'product.template',
           'product.category', 'stock.warehouse', 'stock.location', 'account.move', 'account.move.line', 'purchase.order.line'}


def lire_modeles():
    champs, methodes, bases = {}, {}, {}
    for py in glob.glob('kode_agri_*/models/*.py'):
        for cls in [n for n in ast.walk(ast.parse(open(py).read())) if isinstance(n, ast.ClassDef)]:
            nom = inh = None
            for st in cls.body:
                if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name):
                    t = st.targets[0].id
                    if t == '_name':
                        nom = st.value.value
                    if t == '_inherit':
                        inh = st.value.value if isinstance(st.value, ast.Constant) else [e.value for e in st.value.elts]
            modele = nom or (inh if isinstance(inh, str) else None)
            if not modele:
                continue
            if isinstance(inh, list):
                bases.setdefault(modele, set()).update(inh)
            elif nom and isinstance(inh, str):
                bases.setdefault(modele, set()).add(inh)
            for st in cls.body:
                if isinstance(st, ast.Assign) and isinstance(st.value, ast.Call) and isinstance(st.targets[0], ast.Name):
                    f = st.value.func
                    if isinstance(f, ast.Attribute) and f.attr in CHAMPS:
                        co = st.value.args[0].value if f.attr in ('Many2one', 'One2many', 'Many2many') and st.value.args and isinstance(st.value.args[0], ast.Constant) else None
                        champs.setdefault(modele, {})[st.targets[0].id] = co
                if isinstance(st, ast.FunctionDef):
                    methodes.setdefault(modele, set()).add(st.name)
    return champs, methodes, bases


def heritage(dic, bases, modele, vu=None):
    vu = vu or set()
    out = dict(dic.get(modele, {})) if isinstance(dic.get(modele, {}), dict) else set(dic.get(modele, ()))
    for b in bases.get(modele, ()):
        if b not in vu:
            vu.add(b)
            sous = heritage(dic, bases, b, vu)
            out.update(sous) if isinstance(out, dict) else out.update(sous)
    return out


def verifier_vues(champs, methodes, bases):
    def parcourir(el, modele):
        for ch in el:
            if ch.tag == 'field':
                n = ch.get('name')
                connus = heritage(champs, bases, modele)
                if modele != '?' and (modele.startswith('ka.') or n.startswith('ka_')):
                    if n not in connus and n not in STD and not (modele in ETENDUS and not n.startswith('ka_')):
                        erreurs.append('CHAMP MANQUANT %s.%s' % (modele, n))
                for sub in [c for c in ch if c.tag in ('list', 'form')]:
                    parcourir(sub, connus.get(n) or '?')
            else:
                parcourir(ch, modele)
    for xml in glob.glob('kode_agri_*/views/*.xml'):
        for rec in etree.parse(xml).getroot().iter('record'):
            if rec.get('model') != 'ir.ui.view':
                continue
            modele = rec.find("field[@name='model']").text
            parcourir(rec.find("field[@name='arch']"), modele)
            for b in rec.iter('button'):
                if b.get('type') == 'object' and b.get('name') not in heritage(methodes, bases, modele) \
                        and b.get('name') not in {'action_post', 'action_register_payment', 'button_confirm'}:
                    erreurs.append('BOUTON MANQUANT %s.%s (%s)' % (modele, b.get('name'), xml))


def verifier_manifestes():
    mans, ids = {}, {}
    for m in sorted(glob.glob('kode_agri_*/__manifest__.py')):
        nom = m.split('/')[0]
        mans[nom] = ast.literal_eval(open(m).read())
        for f in mans[nom]['data']:
            if not os.path.exists(os.path.join(nom, f)):
                erreurs.append('FICHIER MANQUANT %s/%s' % (nom, f))
        for f in glob.glob(nom + '/views/*.xml') + glob.glob(nom + '/data/*.xml') + glob.glob(nom + '/security/*.csv'):
            if os.path.relpath(f, nom) not in mans[nom]['data']:
                erreurs.append('FICHIER NON LISTÉ %s' % f)
            if f.endswith('.xml'):
                etree.parse(f)
                ids.setdefault(nom, set()).update(re.findall(r'<(?:record|menuitem) id="([^"]+)"', open(f).read()))
    ordre, vus = [], set()

    def visiter(n, pile=()):
        if n in pile:
            erreurs.append('CYCLE DE DÉPENDANCES %s' % ' → '.join(pile + (n,)))
            return
        if n in vus:
            return
        for d in mans[n]['depends']:
            if d.startswith('kode_agri_'):
                visiter(d, pile + (n,)) if d in mans else erreurs.append('DÉPENDANCE INCONNUE %s → %s' % (n, d))
        vus.add(n)
        ordre.append(n)
    for n in mans:
        visiter(n)
    for f in glob.glob('kode_agri_*/views/*.xml') + glob.glob('kode_agri_*/data/*.xml'):
        mod, t = f.split('/')[0], open(f).read()
        # les expressions eval d'un fichier de données n'ont ni `env` ni la base : ref(), time, DateTime… seulement
        for expr in re.findall(r'eval="([^"]*)"', t):
            if re.search(r"\benv\b|\.search\(|\.browse\(|\bself\b", expr):
                erreurs.append('EVAL INTERDIT (env/search/browse non disponibles dans un fichier de données) : %s dans %s' % (expr[:70], f))
        for attr, i in re.findall(r'\b(ref|action|parent|view_id|inherit_id)="([^"]+)"', t):
            if '.' in i:
                m_, x = i.split('.', 1)
                if m_.startswith('kode_agri_') and x not in ids.get(m_, set()):
                    erreurs.append('XMLID INTROUVABLE %s dans %s' % (i, f))
            elif i not in ids[mod] and not i.startswith('model_'):
                erreurs.append('XMLID SANS PRÉFIXE (cherché dans %s) : %s dans %s' % (mod, i, f))
    for py in glob.glob('kode_agri_*/models/*.py'):
        for m_, x in re.findall(r"env\.ref\(\s*'(kode_agri_[a-z]+)\.([^']+)'", open(py).read()):
            if '%' not in x and x not in ids.get(m_, set()):   # identifiants construits dynamiquement : non vérifiables
                erreurs.append('env.ref INTROUVABLE %s.%s dans %s' % (m_, x, py))
    return ordre


if __name__ == '__main__':
    champs, methodes, bases = lire_modeles()
    ordre = verifier_manifestes()
    verifier_vues(champs, methodes, bases)
    for py in glob.glob('kode_agri_*/**/*.py', recursive=True):
        compile(open(py).read(), py, 'exec')
    print("Ordre d'installation :", ' → '.join(ordre))
    print('%d addons, %d modèles' % (len(ordre), len(champs)))
    for e in sorted(set(erreurs)):
        print('ERREUR', e)
    print('OK : aucune erreur détectée' if not erreurs else '%d erreur(s)' % len(set(erreurs)))
    sys.exit(1 if erreurs else 0)
