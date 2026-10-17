import base64
import csv
import io

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import (MINUS, MOIS, SECTIONS, debut_fin_mois, fmt_dec, fmt_int, fmt_signe, lignes, plan_col, plan_de, section)

MCOLS = ['m%02d' % i for i in range(1, 13)]
VERSIONS = [('initial', 'Initial'), ('revise', 'Révisé'), ('simulation', 'Simulation')]


class KaBudget(models.Model):
    """Budget mensualisé en deux couches : détail (justification) et consolidé (suivi) — § 8.2.1, 8.2.2."""
    _name = 'ka.budget'
    _description = 'Budget'
    _inherit = ['ka.document', 'mail.thread', 'mail.activity.mixin']
    _order = 'annee desc, id desc'

    name = fields.Char(string='Budget', required=True, copy=False, default='Nouveau')
    annee = fields.Integer(string='Année', required=True, default=lambda s: fields.Date.today().year)
    version = fields.Selection(VERSIONS, string='Version', required=True, default='initial')
    revision = fields.Integer(string='Révision', default=0)
    parent_id = fields.Many2one('ka.budget', string='Version précédente', readonly=True, copy=False)
    axe_croise = fields.Char(string='Axe croisé')
    ligne_ids = fields.One2many('ka.budget.ligne', 'budget_id', string='Couche consolidée')
    detail_ids = fields.One2many('ka.budget.detail', 'budget_id', string='Couche de détail')
    total = fields.Float(compute='_compute_total', string='Total (FCFA)', digits=(16, 0))
    ligne_sel_id = fields.Many2one('ka.budget.ligne', string='Montant consolidé à détailler', domain="[('budget_id', '=', id)]")
    mois_sel = fields.Selection([(str(i), MOIS[i - 1]) for i in range(1, 13)], string='Mois')
    detail_sel_ids = fields.Many2many('ka.budget.detail', compute='_compute_detail_sel', string='Détail du montant')
    detail_titre = fields.Char(compute='_compute_detail_sel')
    titre_vue = fields.Char(compute='_compute_titre_vue')
    suivi_html = fields.Html(compute='_compute_suivi', sanitize=False)
    ecart_global_txt = fields.Char(compute='_compute_suivi', string='Écart global')
    state = fields.Selection([('preparation', 'En préparation'), ('a_valider', 'À valider'), ('valide', 'Validé — verrouillé')],
                             default='preparation', string='Statut', tracking=True)
    date_validation = fields.Date(readonly=True, copy=False)

    def _ka_subtitle(self):
        self.ensure_one()
        v = dict(self._fields['version'].selection)[self.version].lower() + (' %s' % self.revision if self.revision else '')
        if self.state == 'valide':
            d = self.date_validation.strftime('%d/%m/%Y') if self.date_validation else ''
            return '%s · version %s · validée et verrouillée (CA du %s)' % (self.name, v, d)
        return '%s · version %s · budget mensualisé par compte et axe analytique' % (self.name, v)

    @api.depends('state')
    def _compute_titre_vue(self):
        for b in self:
            b.titre_vue = 'Saisie des budgets — version validée' if b.state == 'valide' else 'Saisie des budgets — génération de la maquette'

    @api.depends('ligne_ids.total')
    def _compute_total(self):
        for b in self:
            b.total = sum(b.ligne_ids.mapped('total'))

    @api.depends('ligne_sel_id', 'mois_sel')
    def _compute_detail_sel(self):
        for b in self:
            l = b.ligne_sel_id
            if not l:
                b.detail_sel_ids, b.detail_titre = self.env['ka.budget.detail'], ''
                continue
            dets = l.detail_ids
            if b.mois_sel:
                dets = dets.filtered(lambda d: d.date and d.date.month == int(b.mois_sel))
            b.detail_sel_ids = dets
            mont = sum(dets.mapped('montant'))
            b.detail_titre = 'Détail de %s M FCFA — %s × %s%s' % (fmt_dec(mont / 1e6), l.section_id.name or '', l.account_id.code or '', (' × %s' % MOIS[int(b.mois_sel) - 1].lower()) if b.mois_sel else '')

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            if v.get('name', 'Nouveau') == 'Nouveau':
                v['name'] = 'BUD-%s' % v.get('annee', fields.Date.today().year)
        return super().create(vals_list)

    def write(self, vals):
        if any(b.state == 'valide' for b in self) and set(vals) - {'state', 'date_validation', 'ligne_sel_id', 'mois_sel'}:
            raise UserError(_("Ce budget est validé : il n'est plus modifiable. Créez une révision."))
        return super().write(vals)

    def unlink(self):
        if any(b.state == 'valide' for b in self):
            raise UserError(_("Un budget validé ne peut pas être supprimé."))
        return super().unlink()

    # ---- cycle ------------------------------------------------------------------------------------------------------
    def action_soumettre(self):
        self.filtered(lambda b: b.state == 'preparation').write({'state': 'a_valider'})

    def action_valider(self):
        """Verrouille les lignes de détail et la couche consolidée ; le budget fait référence pour le suivi."""
        for b in self:
            if not b.ligne_ids:
                raise UserError(_("Le budget ne contient aucune ligne."))
            b.write({'state': 'valide', 'date_validation': fields.Date.context_today(b)})

    def action_revision(self):
        """Budget validé non modifiable : toute évolution passe par une nouvelle version soumise au circuit de validation."""
        self.ensure_one()
        if self.state != 'valide':
            raise UserError(_("Seul un budget validé se révise."))
        n = self.search_count([('annee', '=', self.annee), ('version', '=', 'revise')]) + 1
        new = self.copy({'name': '%s-R%d' % (self.name.split('-R')[0], n), 'version': 'revise', 'revision': n, 'state': 'preparation',
                         'parent_id': self.id, 'date_validation': False})
        for l in self.ligne_ids:
            nl = l.copy({'budget_id': new.id})
            for d in l.detail_ids:
                d.copy({'budget_id': new.id, 'ligne_id': nl.id})
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.budget', 'res_id': new.id, 'view_mode': 'form'}

    # ---- génération de la maquette à partir du réalisé (§ 8.2.1, 8.2.4) ------------------------------------------------
    def action_generer_maquette(self):
        """Agrège les écritures analytiques de l'année précédente par compte général × section × mois : une ligne de détail
        par écriture (traçabilité, zoom) et une ligne consolidée par clé de regroupement. Rejette les référentiels inconnus."""
        for b in self:
            if b.state == 'valide':
                raise UserError(_("Budget validé : génération impossible."))
            deb, fin = fields.Date.today().replace(year=b.annee - 1, month=1, day=1), fields.Date.today().replace(year=b.annee - 1, month=12, day=31)
            accounts = self.env['account.analytic.account'].search([('code', 'in', [c for c, *_x in SECTIONS])])
            if not accounts:
                raise UserError(_("Les sections de l'axe activité sont introuvables."))
            b.detail_ids.unlink()
            b.ligne_ids.unlink()
            groupes = {}
            for sec in accounts:
                for l in lignes(self.env, sec, deb, fin):
                    if not l.general_account_id:
                        continue                      # compte général inconnu : ligne rejetée
                    groupes.setdefault((l.general_account_id.id, sec.id), []).append(l)
            for (acc_id, sec_id), ls in groupes.items():
                ligne = self.env['ka.budget.ligne'].create({'budget_id': b.id, 'account_id': acc_id, 'section_id': sec_id})
                vals_det = []
                for l in ls:
                    mois = l.date.month
                    ligne[MCOLS[mois - 1]] += -l.amount
                    pu = (-l.amount / l.unit_amount) if l.unit_amount else 0.0
                    vals_det.append({'budget_id': b.id, 'ligne_id': ligne.id, 'type': 'ligne_article' if l.product_id else 'ligne',
                                     'reference': l.ref or l.name, 'intitule': l.name, 'quantite': l.unit_amount, 'pu': pu,
                                     'montant': -l.amount, 'date': l.date.replace(year=b.annee)})
                self.env['ka.budget.detail'].create(vals_det)
                q = sum(ls_.unit_amount for ls_ in ls)
                ligne.write({'quantite': q, 'pu': (ligne.total / q) if q else 0.0})
        return True

    def action_consolider(self):
        """Routine de consolidation : réagrège le détail dans la couche consolidée (relançable à tout moment)."""
        for b in self:
            for l in b.ligne_ids:
                vals = {c: 0.0 for c in MCOLS}
                for d in l.detail_ids:
                    if d.date:
                        vals[MCOLS[d.date.month - 1]] += d.montant
                if l.detail_ids:
                    l.write(vals)

    def action_importer(self):
        self.ensure_one()
        if self.state == 'valide':
            raise UserError(_("Budget validé : import impossible."))
        wiz = self.env['ka.budget.import'].create({'budget_id': self.id})
        return {'type': 'ir.actions.act_window', 'name': 'Importer les budgets', 'res_model': 'ka.budget.import',
                'res_id': wiz.id, 'view_mode': 'form', 'target': 'new'}

    def action_imprimer(self):
        return self.env['ka.structure']._notif(_('Budget'), _("Budget envoyé à l'impression."))

    def action_exporter(self):
        return self.env['ka.structure']._notif(_('Export'), _('Budget exporté.'))

    def action_ouvrir_detail(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Budget consolidé — détail', 'res_model': 'ka.budget', 'res_id': self.id,
                'view_mode': 'form', 'views': [(self.env.ref('kode_agri_gestion.view_ka_budget_detail_form').id, 'form')]}

    def action_ouvrir_suivi(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Budget — suivi par activité', 'res_model': 'ka.budget', 'res_id': self.id,
                'view_mode': 'form', 'views': [(self.env.ref('kode_agri_gestion.view_ka_budget_suivi_form').id, 'form')]}

    # ---- comparaison budget / réalisé (§ 8.2.6) -------------------------------------------------------------------------------
    def _comparer(self):
        """[(code, nom, budget, réalisé)] par section d'activité sur l'année du budget."""
        self.ensure_one()
        deb, fin = fields.Date.today().replace(year=self.annee, month=1, day=1), fields.Date.today().replace(year=self.annee, month=12, day=31)
        out = []
        for code, nom, _etape in SECTIONS:
            acc = section(self.env, code)
            budget = sum(self.ligne_ids.filtered(lambda l: l.section_id == acc).mapped('total'))
            realise = -sum(lignes(self.env, acc, deb, fin).mapped('amount')) if acc else 0.0
            out.append((code, nom, budget, realise))
        return out

    @api.depends('ligne_ids.total', 'annee')
    def _compute_suivi(self):
        axes = {'ACH_FDT': 'Grade TSR10', 'USINAGE': 'Site usine', 'FOB': 'Campagne %s', 'AFV': 'Campagne %s', 'ADMIN': 'Structure'}
        for b in self:
            comp = b._comparer()
            rows = ''.join('<tr><td>%s</td><td>%s</td><td class="o_ka_num">%s</td><td class="o_ka_num">%s</td><td class="o_ka_num">%s</td></tr>' % (
                nom, (axes[code] % b.annee) if '%s' in axes[code] else axes[code], fmt_int(bud), fmt_int(real), fmt_signe(bud - real)) for code, nom, bud, real in comp)
            ecart = sum(bud - real for _c, _n, bud, real in comp)
            b.ecart_global_txt = '%s FCFA' % fmt_signe(ecart)
            b.suivi_html = ('<table class="o_ka_tbl"><thead><tr><th>Section (activité)</th><th>Axe croisé</th><th class="o_ka_num">Budget</th><th class="o_ka_num">Réalisé</th><th class="o_ka_num">Écart</th></tr></thead><tbody>%s</tbody><tfoot><tr><td><b>Écart global</b></td><td></td><td></td><td></td><td class="o_ka_num"><b>%s FCFA</b></td></tr></tfoot></table>' % (rows, fmt_signe(ecart)))

    # ---- alertes (§ 8.5.3) -------------------------------------------------------------------------------------------------
    @api.model
    def cron_alertes(self):
        """Action planifiée : active une alerte lorsque l'écart d'une section dépasse le seuil paramétré."""
        seuil = self.env['ka.gestion.param'].get().seuil_ecart
        for b in self.search([('state', '=', 'valide')]):
            for code, nom, bud, real in b._comparer():
                if bud and abs(real - bud) / bud * 100 > seuil:
                    b.activity_schedule('mail.mail_activity_data_todo', summary=_('Écart budgétaire > %s %% : %s') % (seuil, nom),
                                        user_id=self.env.ref('base.user_admin').id)


class KaBudgetLigne(models.Model):
    """Couche consolidée : clé de regroupement compte général × section d'activité × mois (§ 8.2.4)."""
    _name = 'ka.budget.ligne'
    _description = 'Budget — ligne consolidée'
    _order = 'section_id, account_id'

    budget_id = fields.Many2one('ka.budget', required=True, ondelete='cascade')
    account_id = fields.Many2one('account.account', string='Compte général', required=True)
    section_id = fields.Many2one('account.analytic.account', string='Section (activité)', required=True)
    quantite = fields.Float(string='Qté (t)', digits=(12, 0))
    pu = fields.Float(string='PU (F/kg)', digits=(10, 0))
    m01 = fields.Float(string='Janv.', digits=(16, 0))
    m02 = fields.Float(string='Févr.', digits=(16, 0))
    m03 = fields.Float(string='Mars', digits=(16, 0))
    m04 = fields.Float(string='Avr.', digits=(16, 0))
    m05 = fields.Float(string='Mai', digits=(16, 0))
    m06 = fields.Float(string='Juin', digits=(16, 0))
    m07 = fields.Float(string='Juil.', digits=(16, 0))
    m08 = fields.Float(string='Août', digits=(16, 0))
    m09 = fields.Float(string='Sept.', digits=(16, 0))
    m10 = fields.Float(string='Oct.', digits=(16, 0))
    m11 = fields.Float(string='Nov.', digits=(16, 0))
    m12 = fields.Float(string='Déc.', digits=(16, 0))
    total = fields.Float(compute='_compute_total', string='Total', digits=(16, 0), store=True)
    detail_ids = fields.One2many('ka.budget.detail', 'ligne_id', string='Détail')

    @api.depends(*MCOLS)
    def _compute_total(self):
        for l in self:
            l.total = sum(l[c] for c in MCOLS)

    def _verrou(self):
        if any(l.budget_id.state == 'valide' for l in self):
            raise UserError(_("Ce budget est validé : il n'est plus modifiable. Créez une révision."))

    def write(self, vals):
        if set(vals) - {'detail_ids'}:
            self._verrou()
        return super().write(vals)

    def unlink(self):
        self._verrou()
        return super().unlink()

    @api.constrains('budget_id', 'account_id', 'section_id')
    def _check_cle(self):
        for l in self:
            if self.search_count([('budget_id', '=', l.budget_id.id), ('account_id', '=', l.account_id.id),
                                  ('section_id', '=', l.section_id.id), ('id', '!=', l.id)]):
                raise UserError(_('Doublon : la clé compte × section existe déjà dans ce budget.'))


class KaBudgetDetail(models.Model):
    """Couche de détail : lignes et écritures articles justifiant un montant consolidé."""
    _name = 'ka.budget.detail'
    _description = 'Budget — ligne de détail'
    _order = 'date, id'

    budget_id = fields.Many2one('ka.budget', required=True, ondelete='cascade')
    ligne_id = fields.Many2one('ka.budget.ligne', ondelete='cascade')
    type = fields.Selection([('ligne_article', 'Ligne article'), ('ligne', 'Ligne')], string='Type', default='ligne')
    reference = fields.Char(string='Ligne')
    intitule = fields.Char(string='Article / intitulé')
    quantite = fields.Float(string='Quantité (t)', digits=(12, 0))
    pu = fields.Float(string='PU (F/kg)', digits=(10, 0))
    montant = fields.Float(string='Montant', digits=(16, 0))
    date = fields.Date(string='Date')

    def write(self, vals):
        if any(d.budget_id.state == 'valide' for d in self):
            raise UserError(_("Ce budget est validé : il n'est plus modifiable. Créez une révision."))
        return super().write(vals)

    def unlink(self):
        if any(d.budget_id.state == 'valide' for d in self):
            raise UserError(_("Ce budget est validé : il n'est plus modifiable. Créez une révision."))
        return super().unlink()


class KaBudgetImport(models.TransientModel):
    """Import Excel/CSV : compte général, activité, axe croisé, 12 colonnes mensuelles ; contrôle de cohérence (§ 8.2.1)."""
    _name = 'ka.budget.import'
    _description = 'Importer les budgets'

    budget_id = fields.Many2one('ka.budget', required=True)
    fichier = fields.Binary(string='Fichier CSV (modèle d\'import)')
    nom = fields.Char()
    resultat = fields.Text(readonly=True)

    def action_importer(self):
        self.ensure_one()
        if not self.fichier:
            raise UserError(_("Sélectionnez le fichier d'import."))
        txt = base64.b64decode(self.fichier).decode('utf-8-sig')
        dialect = csv.Sniffer().sniff(txt[:2048], delimiters=';,\t')
        rejets, crees, vus = [], 0, set()
        for i, row in enumerate(csv.DictReader(io.StringIO(txt), dialect=dialect), start=2):
            acc = self.env['account.account'].search([('code', '=', (row.get('compte') or '').strip())], limit=1)
            sec = self.env['account.analytic.account'].search([('code', '=', (row.get('activite') or '').strip())], limit=1)
            if not acc or not sec:
                rejets.append('Ligne %d : %s inconnu' % (i, 'compte général' if not acc else 'section analytique'))
                continue
            if (acc.id, sec.id) in vus:
                rejets.append('Ligne %d : doublon compte × section' % i)
                continue
            vus.add((acc.id, sec.id))
            vals = {'budget_id': self.budget_id.id, 'account_id': acc.id, 'section_id': sec.id}
            for k, c in enumerate(MCOLS, start=1):
                vals[c] = float(str(row.get('m%02d' % k) or row.get(MOIS[k - 1]) or 0).replace(' ', '').replace(',', '.') or 0)
            self.env['ka.budget.ligne'].create(vals)
            crees += 1
        self.resultat = '%d ligne(s) importée(s), %d rejetée(s).\n%s' % (crees, len(rejets), '\n'.join(rejets))
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'target': 'new'}
