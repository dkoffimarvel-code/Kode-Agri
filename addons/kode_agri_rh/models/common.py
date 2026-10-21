from odoo import _
from odoo.exceptions import UserError

MOIS = ('Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet', 'Août', 'Septembre', 'Octobre',
        'Novembre', 'Décembre')


def compte(env, code):
    """Compte du plan comptable par son code exact, à défaut par préfixe (plans à 6 ou 8 chiffres)."""
    Acc = env['account.account']
    acc = Acc.search([('code', '=', code)], limit=1) or Acc.search([('code', '=like', code + '%')], order='code', limit=1)
    racine = code.rstrip('0')
    while not acc and len(racine) >= 3:   # 661100 → 6611… → 661… (plans complétés par des zéros)
        acc = Acc.search([('code', '=like', racine + '%')], order='code', limit=1)
        racine = racine[:-1]
    if not acc:
        raise UserError(_("Le compte %s est introuvable dans le plan comptable.") % code)
    return acc


def journal(env, code, typ='general'):
    J = env['account.journal']
    dom = [('company_id', '=', env.company.id)]
    return J.search(dom + [('code', '=', code)], limit=1) \
        or J.search(dom + [('type', '=', typ), ('code', 'in', ('OD', 'MISC', 'DIV'))], limit=1) \
        or J.search(dom + [('type', '=', typ)], order='sequence, id', limit=1)


def fcfa(montant):
    """185000 → « 185 000 »."""
    return '{:,.0f}'.format(montant or 0).replace(',', ' ')


def heures(h):
    """8.1 → « 8h06 »."""
    h = h or 0.0
    signe = '-' if h < 0 else ''
    m = int(round(abs(h) * 60))
    return '%s%dh%02d' % (signe, m // 60, m % 60)


def mois_txt(d):
    return '%s %s' % (MOIS[d.month - 1], d.year) if d else ''


def anciennete(debut, fin):
    """Ancienneté en mois révolus et libellé « 2 ans, 3 mois »."""
    if not debut or not fin or fin < debut:
        return 0, ''
    mois = (fin.year - debut.year) * 12 + fin.month - debut.month - (1 if fin.day < debut.day else 0)
    a, m = divmod(max(mois, 0), 12)
    txt = ', '.join(x for x in ('%d an%s' % (a, 's' if a > 1 else '') if a else '',
                                 '%d mois' % m if m or not a else '') if x)
    return mois, txt
