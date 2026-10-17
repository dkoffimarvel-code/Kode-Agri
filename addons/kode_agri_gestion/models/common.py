from datetime import date

from dateutil.relativedelta import relativedelta

# Axe ACTIVITE : cascade du coût de revient (§ 8.1.1)
SECTIONS = [
    ('ACH_FDT', "Coût d'achat FDT", 'Coût matière'),
    ('USINAGE', "Coût d'usinage", 'Coût de production'),
    ('FOB', 'Frais de mise à FOB', 'Coût de revient FOB'),
    ('AFV', 'Autres frais sur vente', 'Coût commercial'),
    ('ADMIN', 'Frais administratifs', 'Coût complet'),
]
MOIS = ['Janv.', 'Févr.', 'Mars', 'Avr.', 'Mai', 'Juin', 'Juil.', 'Août', 'Sept.', 'Oct.', 'Nov.', 'Déc.']
MOIS_LONG = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
MINUS = '−'


def fmt_int(x):
    """Entier avec espaces insécables fines comme séparateur de milliers : 28 400 000."""
    return '{:,.0f}'.format(x).replace(',', ' ')


def fmt_par(x):
    """Négatif entre parenthèses : (318)."""
    return '(%s)' % fmt_int(abs(x)) if round(x) < 0 else fmt_int(x)


def fmt_dec(x, n=1):
    s = ('%.*f' % (n, abs(x))).replace('.', ',')
    return (MINUS if round(x, n) < 0 else '') + s


def fmt_signe(x, n=0, unite=''):
    """+ 1 600 000 / − 200 000 (espace entre le signe et le nombre, comme les maquettes)."""
    if round(x, n) == 0:
        return '0' + unite
    base = fmt_int(abs(x)) if n == 0 else ('%.*f' % (n, abs(x))).replace('.', ',')
    return '%s %s%s' % ('+' if x > 0 else MINUS, base, unite)


def plan_col(plan):
    """Nom de la colonne analytique d'un plan sur account.analytic.line (compatibilité multi-plans)."""
    return plan._column_name() if hasattr(plan, '_column_name') else 'account_id'


def plan_de(account):
    return account.root_plan_id if 'root_plan_id' in account._fields else account.plan_id


def analytic_vals(account):
    """Valeurs à inscrire sur une ligne analytique pour rattacher une écriture à un compte."""
    return {'account_id': account.id, plan_col(plan_de(account)): account.id}


def section(env, code):
    return env['account.analytic.account'].search([('code', '=', code)], limit=1)


def lignes(env, accounts, debut, fin, croises=()):
    """Lignes analytiques des comptes (d'un même plan) sur une période, filtrées par des comptes croisés."""
    dom = [('date', '>=', debut), ('date', '<=', fin), ('company_id', '=', env.company.id)]
    if accounts:
        dom.append((plan_col(plan_de(accounts[0])), 'in', accounts.ids))
    dom += [(plan_col(plan_de(acc)), '=', acc.id) for acc in croises if acc]
    return env['account.analytic.line'].search(dom)


def cout(env, code, debut, fin, croises=()):
    """Coût (positif) d'une section d'activité sur la période."""
    acc = section(env, code)
    if not acc:
        return 0.0
    return -sum(lignes(env, acc, debut, fin, croises).mapped('amount'))


def annee(d):
    return d.replace(month=1, day=1), d.replace(month=12, day=31)


def debut_fin_mois(d):
    deb = d.replace(day=1)
    return deb, deb + relativedelta(months=1) - relativedelta(days=1)
