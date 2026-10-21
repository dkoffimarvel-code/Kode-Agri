from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import (MOIS_LONG, SECTIONS, analytic_vals, debut_fin_mois, fmt_dec, fmt_int, lignes, plan_col, plan_de, section)

ETAPES = {code: etape for code, _n, etape in SECTIONS}


class KaCascade(models.Model):
    """Consultation analytique : cascade du coût de revient par activité, croisée avec grade, campagne et site (écran 9.1)."""
    _name = 'ka.cascade'
    _description = 'Consultation analytique — cascade par activité'
    _inherit = ['ka.document']

    axe_principal = fields.Char(string='Axe principal', default='ACTIVITE — Par activité', readonly=True)
    grade_id = fields.Many2one('account.analytic.account', string='Axe croisé',
                               domain="[('plan_id.name', '=', 'Grade')]")
    campagne_id = fields.Many2one('account.analytic.account', string='Campagne', domain="[('plan_id.name', '=', 'Campagne')]")
    site_id = fields.Many2one('account.analytic.account', string='Site', domain="[('plan_id.name', '=', 'Site')]")
    table_html = fields.Html(compute='_compute_table', sanitize=False)
    complet_txt = fields.Char(compute='_compute_table', string='Coût complet')
    part_fdt_txt = fields.Char(compute='_compute_table', string='Part du FDT')
    titre = fields.Char(compute='_compute_table')

    def _ka_subtitle(self):
        self.ensure_one()
        return self.titre

    def _annee(self):
        """Année de la campagne choisie (code ou nom du compte, ex. « 2026 »), sinon année en cours."""
        self.ensure_one()
        for txt in (self.campagne_id.code, self.campagne_id.name):
            if txt and str(txt).strip()[:4].isdigit():
                return int(str(txt).strip()[:4])
        return fields.Date.today().year

    @api.depends('grade_id', 'campagne_id', 'site_id')
    def _compute_table(self):
        for c in self:
            croises = [x for x in (c.grade_id, c.campagne_id, c.site_id) if x]
            annee = c._annee()
            debut, fin = fields.Date.today().replace(year=annee, month=1, day=1), fields.Date.today().replace(year=annee, month=12, day=31)
            montants = {}
            for code, _nom, _etape in SECTIONS:
                acc = section(self.env, code)
                montants[code] = -sum(lignes(self.env, acc, debut, fin, croises).mapped('amount')) if acc else 0.0
            total, cumul, rows = sum(montants.values()), 0.0, []
            for code, nom, etape in SECTIONS:
                cumul += montants[code]
                rows.append('<tr><td>%s</td><td class="o_ka_num">%s</td><td class="o_ka_num">%s</td><td>%s</td></tr>' % (nom, fmt_int(montants[code]), fmt_int(cumul), etape))
            foot = '<tr><td><b>Coût complet</b></td><td></td><td class="o_ka_num"><b>%s</b></td><td><b>Marge nette = prix FOB − coût complet</b></td></tr>' % fmt_int(total)
            c.table_html = ('<table class="o_ka_tbl"><thead><tr><th>Section (activité)</th><th class="o_ka_num">Montant</th><th class="o_ka_num">Cumul</th><th>Étape de la cascade</th></tr></thead><tbody>%s</tbody><tfoot>%s</tfoot></table>' % (''.join(rows), foot))
            c.complet_txt = '%s M FCFA' % fmt_dec(total / 1e6)
            c.part_fdt_txt = '%s %%' % fmt_dec((montants['ACH_FDT'] / total * 100) if total else 0, 0)
            autres = ' et '.join('%s = %s' % (x.plan_id.name.upper(), x.name) for x in croises)
            c.titre = 'Axe ACTIVITE · croisé avec ' + (autres if autres else 'aucun axe')

    def action_actualiser(self):
        self.ensure_one()
        self._compute_table()
        return True

    def action_exporter(self):
        return self.env['ka.structure']._notif(_('Export'), _('Consultation exportée.'))

    def action_detail(self):
        self.ensure_one()
        acc = self.env['account.analytic.account'].search([('code', 'in', [c for c, *_x in SECTIONS])])
        dom = [(plan_col(plan_de(acc[0])), 'in', acc.ids)] if acc else []
        return {'type': 'ir.actions.act_window', 'name': 'Détail des écritures', 'res_model': 'account.analytic.line',
                'view_mode': 'list,form', 'domain': dom}


class KaUo(models.Model):
    """Unité d'œuvre : quantité non financière saisie quotidiennement par section consommatrice (§ 9.1.3)."""
    _name = 'ka.uo'
    _description = "Unité d'œuvre"
    _order = 'date desc, id desc'

    date = fields.Date(required=True, default=fields.Date.context_today)
    emetteur_id = fields.Many2one('account.analytic.account', string='Section émettrice', required=True)
    unite = fields.Char(string="Unité d'œuvre", required=True, default='km')
    recepteur_id = fields.Many2one('account.analytic.account', string='Section réceptrice', required=True)
    quantite = fields.Float(string='Quantité', digits=(12, 0), required=True)


class KaRepartition(models.Model):
    """Répartition analytique d'une charge indirecte : unités d'œuvre → clés en % → répartition par compte général (écran 9.2)."""
    _name = 'ka.repartition'
    _description = 'Répartition analytique — unités d\'œuvre et clés'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'periode desc, id desc'

    name = fields.Char(string='N° répartition', readonly=True, copy=False, default='Nouveau')
    emetteur_id = fields.Many2one('account.analytic.account', string='Charge indirecte', required=True)
    periode = fields.Date(string='Période', required=True, help="Premier jour du mois")
    uo_ids = fields.Many2many('ka.uo', compute='_compute_uo', string="Unités d'œuvre saisies")
    cle_ids = fields.One2many('ka.repartition.cle', 'repartition_id', string='Clés de répartition')
    table_html = fields.Html(compute='_compute_table', sanitize=False)
    state = fields.Selection([('saisie', 'Unités saisies'), ('cles', 'Clés calculées'), ('repartie', 'Répartie')], default='saisie',
                             string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        mois = '%s %s' % (MOIS_LONG[self.periode.month - 1], self.periode.year) if self.periode else ''
        return 'Charge indirecte %s · %s' % (self.emetteur_id.display_name or '', mois)

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            if v.get('name', 'Nouveau') == 'Nouveau':
                v['name'] = self.env['ir.sequence'].next_by_code('ka.repartition')
        return super().create(vals_list)

    def _domaine_uo(self):
        self.ensure_one()
        deb, fin = debut_fin_mois(self.periode)
        return [('emetteur_id', '=', self.emetteur_id.id), ('date', '>=', deb), ('date', '<=', fin)]

    @api.depends('emetteur_id', 'periode')
    def _compute_uo(self):
        for r in self:
            r.uo_ids = self.env['ka.uo'].search(r._domaine_uo()) if r.emetteur_id and r.periode else self.env['ka.uo']

    def action_saisir_uo(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': "Unités d'œuvre", 'res_model': 'ka.uo', 'view_mode': 'list,form',
                'domain': self._domaine_uo(), 'context': {'default_emetteur_id': self.emetteur_id.id, 'default_date': self.periode}}

    def action_calculer_cles(self):
        """À la fin du mois : clé en % de chaque section réceptrice = unités d'œuvre cumulées / total."""
        for r in self:
            uos = self.env['ka.uo'].search(r._domaine_uo())
            total = sum(uos.mapped('quantite'))
            if not total:
                raise UserError(_("Aucune unité d'œuvre saisie pour cette charge indirecte sur la période."))
            par_recepteur = {}
            for u in uos:
                par_recepteur[u.recepteur_id] = par_recepteur.get(u.recepteur_id, 0.0) + u.quantite
            r.cle_ids.unlink()
            r.cle_ids = [Command.create({'recepteur_id': acc.id, 'quantite': q, 'pct': q / total * 100.0})
                         for acc, q in par_recepteur.items()]
            r.state = 'cles'

    def _charges(self):
        """Montants imputés à la charge indirecte, par compte général (positif = charge)."""
        self.ensure_one()
        deb, fin = debut_fin_mois(self.periode)
        out = {}
        for l in lignes(self.env, self.emetteur_id, deb, fin):
            out[l.general_account_id] = out.get(l.general_account_id, 0.0) - l.amount
        return out

    @api.depends('cle_ids.pct', 'emetteur_id', 'periode')
    def _compute_table(self):
        for r in self:
            if not (r.emetteur_id and r.periode):
                r.table_html = ''
                continue
            charges = r._charges()
            cles = r.cle_ids
            tete = ''.join('<th class="o_ka_num">%s %s %%</th>' % (c.recepteur_id.name, fmt_dec(c.pct, 0)) for c in cles)
            rows, tot_recep = [], [0.0] * len(cles)
            for acc, m in charges.items():
                parts = [m * c.pct / 100.0 for c in cles]
                tot_recep = [t + p for t, p in zip(tot_recep, parts)]
                rows.append('<tr><td>%s</td><td class="o_ka_num">%s</td>%s</tr>' % (
                    '%s %s' % (acc.code, acc.name) if acc else '—', fmt_dec(m / 1e6, 2), ''.join('<td class="o_ka_num">%s</td>' % fmt_dec(p / 1e6, 2) for p in parts)))
            tot = sum(charges.values())
            foot = '<tr><td><b>Total %s</b></td><td class="o_ka_num"><b>%s</b></td>%s</tr>' % (
                r.emetteur_id.code or r.emetteur_id.name, fmt_dec(tot / 1e6, 2), ''.join('<td class="o_ka_num"><b>%s</b></td>' % fmt_dec(t / 1e6, 2) for t in tot_recep))
            r.table_html = ('<table class="o_ka_tbl"><thead><tr><th>Compte réparti</th><th class="o_ka_num">Montant</th>%s</tr></thead><tbody>%s</tbody><tfoot>%s</tfoot></table>' % (tete, ''.join(rows), foot))

    def action_repartir(self):
        """Reventile chaque compte général imputé à la charge indirecte avec la clé du mois : une ligne analytique d'extourne
        sur la section émettrice et une ligne par section réceptrice, conservant le compte général (lisibilité par nature)."""
        for r in self:
            if r.state != 'cles':
                raise UserError(_("Calculez d'abord les clés de répartition."))
            _deb, fin = debut_fin_mois(r.periode)
            vals = []
            for acc, m in r._charges().items():
                vals.append(dict(analytic_vals(r.emetteur_id), name='Répartition %s' % r.name, date=fin, amount=m, general_account_id=acc.id,
                                 company_id=self.env.company.id, ref=r.name))
                for c in r.cle_ids:
                    vals.append(dict(analytic_vals(c.recepteur_id), name='Répartition %s' % r.name, date=fin,
                                     amount=-m * c.pct / 100.0, general_account_id=acc.id, company_id=self.env.company.id, ref=r.name))
            self.env['account.analytic.line'].create(vals)
            r.state = 'repartie'


class KaRepartitionCle(models.Model):
    _name = 'ka.repartition.cle'
    _description = 'Clé de répartition'

    repartition_id = fields.Many2one('ka.repartition', required=True, ondelete='cascade')
    recepteur_id = fields.Many2one('account.analytic.account', string='Section réceptrice', required=True)
    quantite = fields.Float(string="Unités d'œuvre", digits=(12, 0))
    pct = fields.Float(string='Clé (%)', digits=(6, 2))
