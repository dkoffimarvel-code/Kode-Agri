from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

from .common import (MINUS, MOIS, MOIS_LONG, SECTIONS, cout, debut_fin_mois, fmt_dec, fmt_int, fmt_par, fmt_signe, lignes, plan_col,
                     plan_de, section)

GRADES = ['TSR10', 'TSR20', 'OFFSPECS']


def _tonnage(env, deb, fin):
    """Production en tonnes : colis validés sur la période."""
    colis = env['ka.colis'].search([('state', '=', 'valide'), ('create_date', '>=', deb), ('create_date', '<=', fin.strftime('%Y-%m-%d 23:59:59'))])
    return sum(colis.mapped('qty')) / 1000.0


def _chiffre_affaires(env, deb, fin):
    """Chiffre d'affaires FOB : produits (comptes de classe 7) des factures de vente validées."""
    l = env['account.move.line'].search([('account_id.account_type', '=', 'income'), ('parent_state', '=', 'posted'), ('date', '>=', deb),
                                         ('date', '<=', fin), ('company_id', '=', env.company.id)])
    return -sum(l.mapped('balance'))


class KaKpi(models.Model):
    """Tableau de bord de pilotage : KPI, marge par grade, coût standard / réel (écran 9.5)."""
    _name = 'ka.kpi'
    _description = 'Tableau de bord de pilotage'
    _inherit = ['ka.document']

    mois = fields.Date(string='Mois', default=lambda s: fields.Date.today().replace(day=1))
    cout_fob = fields.Char(compute='_compute_kpi', string='Coût de revient FOB')
    marge_nette = fields.Char(compute='_compute_kpi', string='Marge nette export')
    tonnage = fields.Char(compute='_compute_kpi', string='Tonnage usiné (mois)')
    rendement = fields.Char(compute='_compute_kpi', string='Rendement usinage')
    ecart_budget = fields.Char(compute='_compute_kpi', string='Écart budget global')
    tresorerie = fields.Char(compute='_compute_kpi', string='Trésorerie nette')
    commentaire = fields.Char(compute='_compute_kpi')
    grades_html = fields.Html(compute='_compute_kpi', sanitize=False)
    couts_html = fields.Html(compute='_compute_kpi', sanitize=False)
    titre = fields.Char(compute='_compute_kpi')
    cartes_html = fields.Html(compute='_compute_kpi', sanitize=False, string='Indicateurs')

    def _ka_subtitle(self):
        self.ensure_one()
        return self.titre

    @api.depends('mois')
    def _compute_display_name(self):
        for k in self:
            m = k.mois or fields.Date.today()
            k.display_name = 'Pilotage — %s %s' % (MOIS_LONG[m.month - 1], m.year)

    @staticmethod
    def _carte(libelle, valeur, sous, couleur):
        """Carte KPI de l'écran 9.5 : liseré de couleur, libellé, valeur, commentaire coloré."""
        teintes = {'ok': '#28a745', 'ko': '#dc3545', 'info': '#0d6efd', 'teal': '#17a2b8'}
        c = teintes[couleur]
        return ('<div class="o_ka_kpi" style="border-left:6px solid %s"><span class="o_ka_kl">%s</span>'
                '<span class="o_ka_kv" style="color:inherit">%s</span><span style="color:%s;font-size:.85rem">%s</span></div>' % (c, libelle, valeur, c, sous))

    def _marge_par_grade(self, deb, fin):
        out = []
        for g in GRADES:
            acc = self.env['account.analytic.account'].search([('code', '=', g)], limit=1)
            l = self.env['account.move.line'].search([('move_id.move_type', '=', 'out_invoice'), ('parent_state', '=', 'posted'), ('product_id.default_code', '=', g),
                                                      ('date', '>=', deb), ('date', '<=', fin)])
            kg = sum(l.mapped('quantity')) * 1000.0
            ca = -sum(l.mapped('balance'))
            cout_g = -sum(lignes(self.env, self.env['account.analytic.account'], deb, fin, [acc]).mapped('amount')) if acc else 0.0
            out.append((g, ((ca - cout_g) / kg) if kg else 0.0))
        return out

    @api.depends('mois')
    def _compute_kpi(self):
        param = self.env['ka.gestion.param'].get()
        for k in self:
            mois = k.mois or fields.Date.today().replace(day=1)
            m_deb, m_fin = debut_fin_mois(mois)
            a_deb, a_fin = mois.replace(month=1, day=1), mois.replace(month=12, day=31)
            t_mois = _tonnage(self.env, m_deb, m_fin)
            t_camp = _tonnage(self.env, a_deb, m_fin)
            fob = sum(cout(self.env, c, a_deb, m_fin) for c in ('ACH_FDT', 'USINAGE', 'FOB'))
            complet = fob + sum(cout(self.env, c, a_deb, m_fin) for c in ('AFV', 'ADMIN'))
            ca = _chiffre_affaires(self.env, a_deb, m_fin)
            fdt = sum(self.env['ka.of.lot'].search([('consomme', '=', True), ('of_id.date_lancement', '>=', m_deb), ('of_id.date_lancement', '<=', m_fin)]).mapped('qty')) / 1000.0
            budget = self.env['ka.budget'].search([('state', '=', 'valide'), ('annee', '=', mois.year)], order='revision desc', limit=1)
            ecart = 0.0
            if budget:
                comp = budget._comparer()
                tb = sum(b for _c, _n, b, _r in comp)
                ecart = ((sum(r for _c, _n, _b, r in comp) - tb) / tb * 100.0) if tb else 0.0
            treso = self.env.ref('kode_agri_compta.treso_1')
            solde = treso._solde_initial()
            lundi = fields.Date.today() - timedelta(days=fields.Date.today().weekday())
            semaines = [('S', lundi + timedelta(weeks=i), lundi + timedelta(weeks=i, days=6)) for i in range(6)]
            prev = treso._collecter(semaines)
            sortie_jour = abs(sum(prev[r][i] for r in ('achats_fdt', 'achats_fg', 'personnel', 'transport') for i in range(6))) / 42.0
            k.cout_fob = '%s F/kg' % fmt_int((fob / (t_camp * 1000)) if t_camp else 0)
            k.marge_nette = '%s %%' % fmt_dec(((ca - complet) / ca * 100) if ca else 0)
            k.tonnage = '%s t' % fmt_int(t_mois)
            k.rendement = '%s %%' % fmt_dec((t_mois / fdt * 100) if fdt else 0)
            k.ecart_budget = '%s %%' % fmt_signe(ecart, 1)
            k.tresorerie = '%s MFCFA' % fmt_dec(solde / 1e6, 0)
            jours = (solde / sortie_jour) if sortie_jour else 0
            k.commentaire = 'Objectif coût FOB : %s F/kg · rendement cible %s %% · couverture de trésorerie %s jours.' % (
                fmt_int(param.cible_fob), fmt_dec(param.cible_rendement, 0), fmt_int(jours))
            k.titre = 'Campagne %s · %s · temps réel' % (mois.year, MOIS_LONG[mois.month - 1])
            # commentaires des cartes : objectif, N-1, plan, cible, sens de l'écart, couverture
            n1 = relativedelta(years=1)
            ca_n1 = _chiffre_affaires(self.env, a_deb - n1, m_fin - n1)
            complet_n1 = sum(cout(self.env, c, a_deb - n1, m_fin - n1) for c in ('ACH_FDT', 'USINAGE', 'FOB', 'AFV', 'ADMIN'))
            marge = ((ca - complet) / ca * 100) if ca else 0.0
            marge_n1 = ((ca_n1 - complet_n1) / ca_n1 * 100) if ca_n1 else 0.0
            plan = 0.0
            if budget:
                usinage = section(self.env, 'USINAGE')
                plan = sum(budget.ligne_ids.filtered(lambda l: l.section_id == usinage).mapped('quantite')) / 12.0
            cout_kg = (fob / (t_camp * 1000)) if t_camp else 0
            rdt = (t_mois / fdt * 100) if fdt else 0
            k.cartes_html = '<div class="o_ka_kpigrid">%s</div>' % ''.join([
                self._carte('Coût de revient FOB', k.cout_fob, 'Objectif : %s' % fmt_int(param.cible_fob), 'ko' if cout_kg > param.cible_fob else 'ok'),
                self._carte('Marge nette export', k.marge_nette, '%s pt vs N-1' % fmt_signe(marge - marge_n1, 1), 'ok' if marge >= marge_n1 else 'ko'),
                self._carte('Tonnage usiné (mois)', k.tonnage, ('%s %% du plan' % fmt_int(t_mois / plan * 100)) if plan else 'Plan non budgété', 'info'),
                self._carte('Rendement usinage', k.rendement, 'Cible : %s %%' % fmt_dec(param.cible_rendement, 0), 'ok' if rdt >= param.cible_rendement else 'ko'),
                self._carte('Écart budget global', k.ecart_budget, 'Défavorable' if ecart > 0 else 'Favorable', 'ko' if ecart > 0 else 'ok'),
                self._carte('Trésorerie nette', k.tresorerie, 'Couverture %s j' % fmt_int(jours), 'teal'),
            ])
            marges = k._marge_par_grade(a_deb, m_fin)
            maxi = max([abs(m) for _g, m in marges] + [1])
            barres = ''.join(
                '<div style="display:flex;flex-direction:column;align-items:center;justify-content:flex-end;width:6rem">'
                '<b>%s</b><div style="width:4.5rem;height:%dpx;background:%s;margin-top:.3rem"></div><b style="margin-top:.3rem">%s</b></div>' % (
                    fmt_int(m), max(int(abs(m) / maxi * 180), 2), '#28a745' if m >= maxi / 2 else '#dc3545', g) for g, m in marges)
            k.grades_html = ('<div style="display:flex;align-items:flex-end;gap:2.5rem;height:250px;border:1px solid #dee2e6;border-radius:4px;'
                             'padding:1rem 2rem">%s</div>' % barres)
            rows = []
            for i in range(3, -1, -1):
                d = (mois - relativedelta(months=i))
                deb, fin = debut_fin_mois(d)
                t = _tonnage(self.env, deb, fin) * 1000
                reel = (cout(self.env, 'USINAGE', deb, fin) / t) if t else 0.0
                ec = ((reel / param.standard_usinage - 1) * 100) if param.standard_usinage else 0
                rows.append('<tr><td>%s</td><td class="o_ka_num">%s</td><td class="o_ka_num">%s</td><td class="o_ka_num %s">%s %%</td></tr>' % (
                    MOIS_LONG[d.month - 1].capitalize(), fmt_int(param.standard_usinage), fmt_int(reel), 'o_ka_ko_txt' if ec > 0 else 'o_ka_ok_txt', fmt_signe(ec, 1)))
            k.couts_html = '<table class="o_ka_tbl"><thead><tr><th>Mois</th><th class="o_ka_num">Standard</th><th class="o_ka_num">Réel</th><th class="o_ka_num">Écart</th></tr></thead><tbody>%s</tbody></table>' % ''.join(rows)

    def action_actualiser(self):
        self._compute_kpi()
        return True

    def action_exporter(self):
        return self.env['ka.structure']._notif(_('Export'), _('Tableau de bord exporté.'))

    def action_parametrer(self):
        return {'type': 'ir.actions.act_window', 'name': 'Paramétrer les indicateurs', 'res_model': 'ka.gestion.param',
                'res_id': self.env['ka.gestion.param'].get().id, 'view_mode': 'form'}


class KaPnl(models.Model):
    """Compte de résultat de gestion par activité : mois, cumul campagne, % CA, N-1 (écran 9.6)."""
    _name = 'ka.pnl'
    _description = 'Compte de résultat de gestion'
    _inherit = ['ka.document']

    mois = fields.Date(string='Mois', default=lambda s: fields.Date.today().replace(day=1))
    table_html = fields.Html(compute='_compute_table', sanitize=False)

    def _ka_subtitle(self):
        return 'P&L de gestion par activité · mois et cumul campagne · montants en MFCFA'

    @api.depends('mois')
    def _compute_display_name(self):
        for p in self:
            m = p.mois or fields.Date.today()
            p.display_name = 'P&L — %s %s' % (MOIS_LONG[m.month - 1], m.year)

    def _valeurs(self, deb_m, fin_m, deb_c, fin_c):
        """{rubrique: (mois, cumul)} en millions, coûts négatifs."""
        v = {'ca': (_chiffre_affaires(self.env, deb_m, fin_m) / 1e6, _chiffre_affaires(self.env, deb_c, fin_c) / 1e6)}
        for code, _n, _e in SECTIONS:
            v[code] = (-cout(self.env, code, deb_m, fin_m) / 1e6, -cout(self.env, code, deb_c, fin_c) / 1e6)
        return v

    @api.depends('mois')
    def _compute_table(self):
        for p in self:
            mois = p.mois or fields.Date.today().replace(day=1)
            deb_m, fin_m = debut_fin_mois(mois)
            deb_c = mois.replace(month=1, day=1)
            cur = p._valeurs(deb_m, fin_m, deb_c, fin_m)
            n1 = p._valeurs(deb_m - relativedelta(years=1), fin_m - relativedelta(years=1), deb_c - relativedelta(years=1), fin_m - relativedelta(years=1))

            def tot(v, i, codes):
                return sum(v[c][i] for c in codes)
            lignes_ = [('Chiffre d\'affaires FOB', 'ca', False), ("Coût d'achat FDT", 'ACH_FDT', False), ("Coût d'usinage", 'USINAGE', False),
                       ('Frais de mise à FOB', 'FOB', False)]
            rows = []
            ca_c = cur['ca'][1]

            def ligne(lib, m, c, n, gras=False):
                pct = (abs(c) / ca_c * 100) if ca_c else 0
                var = ((c - n) / abs(n) * 100) if n else 0
                cls = ' class="o_ka_total"' if gras else ''
                b0, b1 = ('<b>', '</b>') if gras else ('', '')
                sens = 'o_ka_ko_txt' if round(var, 1) > 0 else ('o_ka_ok_txt' if round(var, 1) < 0 else '')
                return '<tr%s><td>%s%s%s</td><td class="o_ka_num">%s%s%s</td><td class="o_ka_num">%s%s%s</td><td class="o_ka_num">%s%s %%%s</td><td class="o_ka_num">%s%s%s</td><td class="o_ka_num %s">%s%s %%%s</td></tr>' % (
                    cls, b0, lib, b1, b0, fmt_par(m), b1, b0, fmt_par(c), b1, b0, fmt_dec(pct), b1, b0, fmt_par(n), b1, sens, b0, fmt_signe(var, 1), b1)
            for lib, code, _g in lignes_:
                rows.append(ligne(lib, cur[code][0], cur[code][1], n1[code][1]))
            marge = [tot(cur, i, ['ca', 'ACH_FDT', 'USINAGE', 'FOB']) for i in (0, 1)]
            marge_n1 = tot(n1, 1, ['ca', 'ACH_FDT', 'USINAGE', 'FOB'])
            rows.append(ligne('Marge sur coût de revient FOB', marge[0], marge[1], marge_n1, True))
            for lib, code in (('Autres frais sur vente', 'AFV'), ('Frais administratifs', 'ADMIN')):
                rows.append(ligne(lib, cur[code][0], cur[code][1], n1[code][1]))
            res = [tot(cur, i, ['ca'] + [c for c, *_x in SECTIONS]) for i in (0, 1)]
            res_n1 = tot(n1, 1, ['ca'] + [c for c, *_x in SECTIONS])
            rows.append(ligne('Résultat de gestion', res[0], res[1], res_n1, True))
            p.table_html = '<table class="o_ka_tbl"><thead><tr><th>Rubrique</th><th class="o_ka_num">Mois (MFCFA)</th><th class="o_ka_num">Cumul (MFCFA)</th><th class="o_ka_num">%% CA</th><th class="o_ka_num">N-1 cumul</th><th class="o_ka_num">Var.</th></tr></thead><tbody>%s</tbody></table>' % ''.join(rows)

    def action_imprimer(self):
        return self.env['ka.structure']._notif(_('P&L'), _("Compte de résultat de gestion envoyé à l'impression."))

    def action_exporter(self):
        return self.env['ka.structure']._notif(_('Export'), _('P&L exporté.'))

    def action_comparer(self):
        self._compute_table()
        return True


class KaTresoGlissant(models.Model):
    """Tableau de trésorerie glissant : réalisé de la semaine précédente et prévisionnel sur quatre semaines (écran 9.7)."""
    _name = 'ka.treso.glissant'
    _description = 'Tableau de trésorerie glissant'
    _inherit = ['ka.document']

    date_ref = fields.Date(string='Situation au', default=fields.Date.context_today)
    table_html = fields.Html(compute='_compute_table', sanitize=False)
    alerte = fields.Char(compute='_compute_table')
    seuil_txt = fields.Char(compute='_compute_table')
    sous_seuil = fields.Boolean(compute='_compute_table')

    def _ka_subtitle(self):
        return 'Réalisé et prévisionnel glissant sur six semaines · montants en MFCFA'

    @api.depends('date_ref')
    def _compute_display_name(self):
        for t in self:
            t.display_name = 'Trésorerie glissante au %s' % (t.date_ref or fields.Date.today()).strftime('%d/%m/%Y')

    def action_imprimer(self):
        return self.env['ka.structure']._notif(_('Trésorerie'), _("Tableau de trésorerie envoyé à l'impression."))

    FLUX = [
        ('enc_export', 'Encaissements export (lettres de crédit)', ['ventes_export']),
        ('enc_autres', 'Autres encaissements', ['ventes_locales', 'autres_produits']),
        ('fdt', 'Achats FDT (avances, collecte)', ['achats_fdt']),
        ('charges', "Charges d'usinage & logistique", ['achats_fg', 'transport', 'investissement']),
        ('salaires', 'Salaires & frais de structure', ['personnel', 'impots']),
        ('dette', 'Service de la dette / frais financiers', ['emprunts', 'spots']),
    ]

    def _flux_paiement(self, p):
        cat_c, cat_f = p.partner_id.ka_cat_client, p.partner_id.ka_categorie
        if p.payment_type == 'inbound':
            return 'enc_export' if cat_c == 'export' else 'enc_autres'
        return {'planteur_coop': 'fdt'}.get(cat_f, 'charges')

    @api.depends('date_ref')
    def _compute_table(self):
        param = self.env['ka.gestion.param'].get()
        for t in self:
            d0 = t.date_ref or fields.Date.today()
            lundi = d0 - timedelta(days=d0.weekday())
            treso = self.env.ref('kode_agri_compta.treso_1')
            periodes = [('S courante' if i == 0 else 'S+%d' % i, lundi + timedelta(weeks=i), lundi + timedelta(weeks=i, days=6)) for i in range(5)]
            res = treso._collecter(periodes)
            reel = {k: 0.0 for k, _l, _r in self.FLUX}
            for p in self.env['account.payment'].search([('state', 'in', ('posted', 'paid')), ('date', '>=', lundi - timedelta(weeks=1)), ('date', '<', lundi)]):
                montant = p.currency_id._convert(p.amount, p.company_id.currency_id, p.company_id, p.date)
                reel[t._flux_paiement(p)] += montant if p.payment_type == 'inbound' else -montant
            cols = [[reel[k] for k, _l, _r in self.FLUX]] + [[sum(res[r][i] for r in rubs) for _k, _l, rubs in self.FLUX] for i in range(5)]
            nets = [sum(c) for c in cols]
            fin, solde = [], treso._solde_initial()
            fin.append(solde)
            for n in nets[1:]:
                solde += n
                fin.append(solde)
            seuil = param.seuil_tresorerie
            heads = ''.join('<th class="o_ka_num">%s</th>' % h for h in ['S-1 réel'] + [p[0] for p in periodes])
            body = ''.join('<tr><td>%s</td>%s</tr>' % (lib, ''.join('<td class="o_ka_num">%s</td>' % fmt_par(cols[j][i] / 1e6) for j in range(6))) for i, (_k, lib, _r) in enumerate(self.FLUX))
            body += '<tr class="o_ka_total"><td>Flux net de la période</td>%s</tr>' % ''.join('<td class="o_ka_num">%s</td>' % fmt_par(n / 1e6) for n in nets)
            body += '<tr class="o_ka_total"><td><b>Trésorerie fin de période</b></td>%s</tr>' % ''.join(
                '<td class="o_ka_num"><b>%s</b></td>' % (('<span class="o_ka_tag o_ka_danger">%s</span>' % fmt_int(f / 1e6)) if f < seuil else fmt_int(f / 1e6)) for f in fin)
            t.table_html = '<table class="o_ka_tbl"><thead><tr><th>Flux</th>%s</tr></thead><tbody>%s</tbody></table>' % (heads, body)
            sous = [lab for lab, f in zip(['S-1 réel'] + [p[0] for p in periodes], fin) if f < seuil]
            t.seuil_txt = fmt_int(seuil / 1e6)
            t.sous_seuil = bool(sous)
            t.alerte = ("Alerte (règle de workflow) si la trésorerie prévisionnelle passe sous le seuil de sécurité de %s M FCFA : semaine %s." % (fmt_int(seuil / 1e6), sous[0].replace('S courante', 'courante'))) if sous else (
                "Alerte (règle de workflow) si la trésorerie prévisionnelle passe sous le seuil de sécurité de %s M FCFA : aucun dépassement prévu." % fmt_int(seuil / 1e6))

    def action_actualiser(self):
        self._compute_table()
        return True

    def action_exporter(self):
        return self.env['ka.structure']._notif(_('Export'), _('Tableau exporté.'))


class KaEcartNote(models.Model):
    _name = 'ka.ecart.note'
    _description = "Note d'analyse d'écart"
    _order = 'annee desc, section_code'

    annee = fields.Integer(default=lambda s: fields.Date.today().year, required=True)
    section_code = fields.Selection([(c, n) for c, n, _e in SECTIONS], string='Section (activité)', required=True)
    texte = fields.Char(string='Analyse', required=True)
    plan_action = fields.Char(string="Plan d'action")


class KaEcart(models.Model):
    """Analyse des écarts budget / réalisé par section, avec décomposition et notes d'analyse (écran 9.4, § 9.2.6)."""
    _name = 'ka.ecart'
    _description = 'Analyse des écarts budget / réalisé'
    _inherit = ['ka.document']

    annee = fields.Integer(string='Campagne', default=lambda s: fields.Date.today().year)
    table_html = fields.Html(compute='_compute_table', sanitize=False)
    decomposition = fields.Char(compute='_compute_table')
    favorable = fields.Selection([('favorable', 'Favorable'), ('defavorable', "Défavorable — plan d'action")], compute='_compute_table')
    decomposition_usinage = fields.Char(compute='_compute_table', string="Décomposition de l'écart usinage")

    def _ka_subtitle(self):
        self.ensure_one()
        return 'Cumul campagne %s · axe activité · montants en MFCFA' % self.annee

    @api.depends('annee')
    def _compute_display_name(self):
        for e in self:
            e.display_name = 'Cumul campagne %s' % e.annee

    def _decomposer_usinage(self, budget, realise):
        """Écart usinage = écart sur quantité (tonnage réel − budgété, au coût unitaire budgété) + écart sur prix (le reste)."""
        self.ensure_one()
        usinage = section(self.env, 'USINAGE')
        lignes_b = budget.ligne_ids.filtered(lambda l: l.section_id == usinage) if budget else self.env['ka.budget.ligne']
        q_b, b = sum(lignes_b.mapped('quantite')), sum(lignes_b.mapped('total'))
        deb, fin = fields.Date.today().replace(year=self.annee, month=1, day=1), fields.Date.today().replace(year=self.annee, month=12, day=31)
        q_r = _tonnage(self.env, deb, fin)
        if not (q_b and q_r):
            return "Décomposition de l'écart usinage : non calculable (tonnage budgété ou réalisé absent)."
        pu_b = b / q_b
        e_q = (q_r - q_b) * pu_b
        e_p = realise - q_r * pu_b
        return "Décomposition de l'écart usinage : écart sur quantité (%s MFCFA, rendement) · écart sur prix (%s MFCFA, tarif énergie)" % (
            fmt_signe(e_q / 1e6), fmt_signe(e_p / 1e6))

    @api.depends('annee')
    def _compute_table(self):
        param = self.env['ka.gestion.param'].get()
        for e in self:
            budget = self.env['ka.budget'].search([('annee', '=', e.annee), ('state', '=', 'valide')], order='revision desc', limit=1)
            comp = budget._comparer() if budget else [(c, n, 0.0, cout(self.env, c, fields.Date.today().replace(year=e.annee, month=1, day=1), fields.Date.today().replace(year=e.annee, month=12, day=31))) for c, n, _x in SECTIONS]
            notes = {n.section_code: n.texte for n in self.env['ka.ecart.note'].search([('annee', '=', e.annee)])}
            e.decomposition_usinage = ''
            rows, tb, tr = [], 0.0, 0.0
            for code, nom, b, r in comp:
                tb, tr = tb + b, tr + r
                pct = ((r - b) / b * 100) if b else 0.0
                sens = ' o_ka_ko_txt' if r > b else (' o_ka_ok_txt' if r < b else '')
                rows.append('<tr><td>%s</td><td class="o_ka_num">%s</td><td class="o_ka_num">%s</td><td class="o_ka_num%s">%s</td><td class="o_ka_num%s">%s %%</td><td>%s</td></tr>' % (
                    nom, fmt_int(b / 1e6), fmt_int(r / 1e6), sens, fmt_signe((r - b) / 1e6), sens, fmt_signe(pct, 1), notes.get(code, '')))
                if code == 'USINAGE':
                    e.decomposition_usinage = e._decomposer_usinage(budget, r)
            pct_t = ((tr - tb) / tb * 100) if tb else 0.0
            e.favorable = 'defavorable' if tr > tb else 'favorable'
            sens = ' o_ka_ko_txt' if tr > tb else ' o_ka_ok_txt'
            foot = '<tr><td>TOTAL</td><td class="o_ka_num">%s</td><td class="o_ka_num">%s</td><td class="o_ka_num%s">%s</td><td class="o_ka_num%s">%s %%</td><td>%s</td></tr>' % (
                fmt_int(tb / 1e6), fmt_int(tr / 1e6), sens, fmt_signe((tr - tb) / 1e6), sens, fmt_signe(pct_t, 1),
                dict(self._fields['favorable'].selection)[e.favorable])
            entete = '<tr><th>Activité</th><th class="o_ka_num">Budget (MFCFA)</th><th class="o_ka_num">Réalisé (MFCFA)</th><th class="o_ka_num">Écart</th><th class="o_ka_num">Écart %</th><th>Analyse</th></tr>'
            e.table_html = '<table class="o_ka_tbl"><thead>' + entete + '</thead><tbody>' + ''.join(rows) + '</tbody><tfoot>' + foot + '</tfoot></table>'
            e.decomposition = "Chaque écart significatif (> %s %%) déclenche une note d'analyse et un plan d'action rattachés à l'activité." % fmt_dec(param.seuil_ecart, 0)

    def action_actualiser(self):
        self._compute_table()
        return True

    def action_note(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': "Note d'analyse", 'res_model': 'ka.ecart.note', 'view_mode': 'form', 'target': 'new',
                'context': {'default_annee': self.annee}}

    def action_exporter(self):
        return self.env['ka.structure']._notif(_('Export'), _('Analyse exportée.'))
