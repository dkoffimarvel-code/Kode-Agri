from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models

RUBRIQUES = [
    # code, libellé, groupe, signe
    ('achats_fdt', 'Achats fond de tasse', 'charges', -1),
    ('achats_fg', 'Achats et frais généraux', 'charges', -1),
    ('personnel', 'Charges de personnel', 'charges', -1),
    ('transport', 'Transport et services extérieurs', 'charges', -1),
    ('ventes_locales', 'Ventes locales', 'produits', 1),
    ('ventes_export', 'Ventes export', 'produits', 1),
    ('autres_produits', 'Autres produits', 'produits', 1),
    ('investissement', 'Investissement', None, -1),
    ('emprunts', "Remboursements d'emprunts", None, -1),
    ('spots', 'Remboursements spots', None, -1),
    ('impots', 'Impôts et taxes', None, -1),
]
SIGNES = {c: s for c, _l, _g, s in RUBRIQUES}
MOIS = ['Janv.', 'Févr.', 'Mars', 'Avr.', 'Mai', 'Juin', 'Juil.', 'Août', 'Sept.', 'Oct.', 'Nov.', 'Déc.']


def fmt(x):
    """Millions de FCFA, une décimale, virgule et vrai signe moins (comme la maquette)."""
    v = round(x / 1e6, 1)
    txt = ('%.1f' % abs(v)).replace('.', ',')
    return ('−' if v < 0 else '') + txt


def fmt_kpi(x, signe=False):
    v = x / 1e6
    return '%s%s M FCFA' % (('+ ' if v > 0 else '− ' if v < 0 else '') if signe else ('− ' if v < 0 else ''), ('%.1f' % abs(v)).replace('.', ','))


class KaTresoLigne(models.Model):
    """Prévision manuelle (engagements, emprunts, impôts, spots...) complétant les échéances validées."""
    _name = 'ka.treso.ligne'
    _description = 'Prévision de trésorerie manuelle'
    _order = 'date'

    date = fields.Date(string='Date prévue', required=True)
    rubrique = fields.Selection([(c, l) for c, l, _g, _s in RUBRIQUES], string='Rubrique', required=True)
    libelle = fields.Char(string='Libellé')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    montant = fields.Monetary(string='Montant', help='Saisi en valeur positive ; le signe est déterminé par la rubrique.')


class KaTreso(models.Model):
    """Prévisions de trésorerie en six rubriques : vue mensuelle et vue hebdomadaire (§ 7.6.4, YTRESO)."""
    _name = 'ka.treso'
    _description = 'Prévisions de trésorerie'
    _inherit = ['ka.document']

    mode = fields.Selection([('mensuelle', 'Mensuelle'), ('hebdo', 'Hebdomadaire')], default='mensuelle', required=True)
    date_ref = fields.Date(string='Situation au', default=fields.Date.context_today, required=True)
    nb_periodes = fields.Integer(string='Périodes', default=6)
    solde_depart = fields.Float(compute='_compute_table', digits=(16, 0))
    depart_txt = fields.Char(compute='_compute_table', string='Solde de départ')
    final_txt = fields.Char(compute='_compute_table', string='Solde prévisionnel')
    variation_txt = fields.Char(compute='_compute_table', string='Variation nette')
    table_html = fields.Html(compute='_compute_table', sanitize=False)
    titre = fields.Char(compute='_compute_table')

    def _ka_subtitle(self):
        self.ensure_one()
        return self.titre

    # ---- périodes ---------------------------------------------------------------------------------------------
    def _periodes(self):
        self.ensure_one()
        d0 = self.date_ref
        out = []
        for k in range(self.nb_periodes):
            if self.mode == 'mensuelle':
                deb = d0.replace(day=1) + relativedelta(months=k)
                fin = deb + relativedelta(months=1) - timedelta(days=1)
                lib = MOIS[deb.month - 1]
            else:
                lundi = d0 - timedelta(days=d0.weekday()) + timedelta(weeks=k)
                deb, fin = lundi, lundi + timedelta(days=6)
                lib = 'S. %s' % deb.strftime('%d/%m')
            out.append((lib, deb, fin))
        return out

    def _index(self, periodes, d):
        """Les échéances passées tombent dans la première période ; au-delà de l'horizon, elles sont ignorées."""
        if d < periodes[0][1]:
            return 0
        for i, (_l, deb, fin) in enumerate(periodes):
            if deb <= d <= fin:
                return i
        return None

    # ---- sources ------------------------------------------------------------------------------------------------
    def _rubrique_fournisseur(self, m):
        lignes = m.invoice_line_ids
        if any(l.account_id.code and l.account_id.code.startswith('2') or l.ka_immobilisable for l in lignes):
            return 'investissement'
        cat = m.partner_id.ka_categorie
        return {'planteur_coop': 'achats_fdt', 'transitaire': 'transport'}.get(cat, 'achats_fg')

    def _rubrique_client(self, m):
        return {'export': 'ventes_export', 'local': 'ventes_locales'}.get(m.partner_id.ka_cat_client, 'autres_produits')

    def _collecter(self, periodes):
        """Montants signés par rubrique et par période, en devise société."""
        comp = self.env.company
        res = {c: [0.0] * len(periodes) for c, *_ in RUBRIQUES}
        moves = self.env['account.move'].search([
            ('state', '=', 'posted'), ('move_type', 'in', ('in_invoice', 'in_refund', 'out_invoice', 'out_refund')),
            ('payment_state', 'in', ('not_paid', 'partial')), ('company_id', '=', comp.id)])
        for m in moves:
            d = m.invoice_date_due or m.invoice_date or m.date
            i = self._index(periodes, d)
            if i is None:
                continue
            montant = m.currency_id._convert(m.amount_residual, comp.currency_id, comp, d)
            if m.move_type in ('in_invoice', 'in_refund'):
                rub = self._rubrique_fournisseur(m)
                res[rub][i] += (-1 if m.move_type == 'in_invoice' else 1) * montant
            else:
                rub = self._rubrique_client(m)
                res[rub][i] += (1 if m.move_type == 'out_invoice' else -1) * montant
        for n in self.env['ka.frais.note'].search([('state', '=', 'comptabilisee')]):   # notes de frais à rembourser
            i = self._index(periodes, n.date_compta or self.date_ref)
            if i is not None:
                res['personnel'][i] -= n.total
        for l in self.env['ka.treso.ligne'].search([]):
            i = self._index(periodes, l.date)
            if i is not None:
                res[l.rubrique][i] += SIGNES[l.rubrique] * l.montant
        return res

    def _solde_initial(self):
        journaux = self.env['account.journal'].search([('type', 'in', ('bank', 'cash')), ('company_id', '=', self.env.company.id)])
        comptes = journaux.default_account_id
        if not comptes:
            return 0.0
        lignes = self.env['account.move.line'].search([('account_id', 'in', comptes.ids), ('parent_state', '=', 'posted')])
        return sum(lignes.mapped('balance'))

    # ---- rendu ---------------------------------------------------------------------------------------------------
    @api.depends('mode', 'date_ref', 'nb_periodes')
    def _compute_table(self):
        for t in self:
            periodes = t._periodes()
            res = t._collecter(periodes)
            n = len(periodes)
            sommes = lambda codes: [sum(res[c][i] for c in codes) for i in range(n)]
            ch = [c for c, _l, g, _s in RUBRIQUES if g == 'charges']
            pr = [c for c, _l, g, _s in RUBRIQUES if g == 'produits']
            autres = [c for c, _l, g, _s in RUBRIQUES if g is None]
            s_ch, s_pr = sommes(ch), sommes(pr)
            variation = [s_ch[i] + s_pr[i] + sum(res[c][i] for c in autres) for i in range(n)]
            depart = t._solde_initial()
            soldes, cumul = [], depart
            for v in variation:
                cumul += v
                soldes.append(cumul)

            def ligne(libelle, valeurs, gras=False, total=True, classe=''):
                tag = 'b' if gras else 'span'
                cells = ''.join('<td class="o_ka_num">%s</td>' % fmt(v) for v in valeurs)
                tot = '<td class="o_ka_num">%s</td>' % (fmt(sum(valeurs)) if total else '')
                return '<tr class="%s"><td><%s>%s</%s></td>%s%s</tr>' % (classe, tag, libelle, tag, cells, tot)
            heads = ''.join('<th class="o_ka_num">%s</th>' % lib for lib, _d, _f in periodes)
            rows = [ligne('Type charges', s_ch, True)]
            rows += [ligne(l, res[c]) for c, l, g, _s in RUBRIQUES if g == 'charges']
            rows += [ligne('Types de produits', s_pr, True)]
            rows += [ligne(l, res[c]) for c, l, g, _s in RUBRIQUES if g == 'produits']
            rows += [ligne(l, res[c]) for c, l, g, _s in RUBRIQUES if g is None]
            rows += [ligne('Variation nette', variation, True), ligne('Solde prévisionnel', soldes, True, total=False)]
            t.table_html = ('<table class="o_ka_tbl o_ka_treso"><thead><tr><th>Rubrique</th>%s<th class="o_ka_num">Total</th></tr></thead><tbody>%s</tbody></table>'
                            % (heads, ''.join(rows)))
            t.solde_depart = depart
            t.depart_txt = fmt_kpi(depart)
            t.final_txt = fmt_kpi(soldes[-1] if soldes else depart)
            t.variation_txt = fmt_kpi(sum(variation), signe=True)
            fin = periodes[-1][2]
            if t.mode == 'mensuelle':
                t.titre = 'Comptes caisse et banque consolidés · %s à %s %s · situation au %s' % (
                    MOIS[periodes[0][1].month - 1].lower().rstrip('.'), MOIS[periodes[-1][1].month - 1].lower().rstrip('.'), fin.year,
                    t.date_ref.strftime('%d/%m/%Y'))
            else:
                t.titre = 'Comptes caisse et banque consolidés · semaines %s à %s · situation au %s' % (
                    periodes[0][1].isocalendar()[1], periodes[-1][1].isocalendar()[1], t.date_ref.strftime('%d/%m/%Y'))

    def action_actualiser(self):
        self.ensure_one()
        self._compute_table()
        vue = 'view_ka_treso_form' if self.mode == 'mensuelle' else 'view_ka_treso_hebdo_form'
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'views': [(self.env.ref('kode_agri_compta.' + vue).id, 'form')]}

    def _basculer(self, mode, n):
        self.ensure_one()
        self.write({'mode': mode, 'nb_periodes': n})
        return self.action_actualiser()

    def action_hebdo(self):
        return self._basculer('hebdo', 6)

    def action_mensuelle(self):
        return self._basculer('mensuelle', 6)

    def action_exporter(self):
        return self.env['ka.structure']._notif(_('Export'), _('Prévisions exportées.'))

    def action_imprimer(self):
        return self.env['ka.structure']._notif(_('Prévisions de trésorerie'), _('État envoyé à l\'impression.'))
