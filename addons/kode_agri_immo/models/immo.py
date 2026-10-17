import calendar
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .famille import METHODES


def fin_de_mois(d):
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def calcul_plan(valeur, debut, duree_ans, methode):
    """Échéancier mensuel (fin de mois) : [(date, dotation, cumul)].
    Linéaire : valeur / nombre de mois ; dégressif : taux linéaire × coefficient (1,5 / 2 / 2,5 selon la durée) avec
    bascule en linéaire quand elle est plus favorable. La première mensualité est calculée prorata temporis et la
    dernière solde exactement la valeur d'acquisition."""
    mois = int(duree_ans * 12)
    if not mois or valeur <= 0:
        return []
    nb_jours = calendar.monthrange(debut.year, debut.month)[1]
    prorata = (nb_jours - debut.day + 1) / nb_jours
    nb_periodes = mois if prorata == 1 else mois + 1
    coef = 1.5 if duree_ans <= 4 else 2.0 if duree_ans <= 6 else 2.5
    taux_mensuel = coef / duree_ans / 12.0
    out, cumul = [], 0
    for k in range(nb_periodes):
        reste = valeur - cumul
        restant = nb_periodes - k
        if k == nb_periodes - 1:
            dot = reste                                   # la dernière échéance solde la valeur
        elif methode == 'degressif':
            dot = max(reste * taux_mensuel, reste / restant)
        else:
            dot = valeur / mois
        if k == 0 and methode == 'lineaire':
            dot *= prorata
        dot = min(round(dot), reste)
        if dot <= 0:
            break
        cumul += dot
        out.append((fin_de_mois(debut + relativedelta(months=k)), dot, cumul))
    return out


class KaImmo(models.Model):
    _name = 'ka.immo'
    _description = 'Immobilisation'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='Immobilisation', readonly=True, copy=False, default='Nouveau')
    intitule = fields.Char(string='Intitulé', required=True)
    famille_id = fields.Many2one('ka.immo.famille', string='Famille', required=True)
    site_id = fields.Many2one('ka.site', string='Site')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    valeur = fields.Monetary(string="Valeur d'acquisition", required=True)
    date_service = fields.Date(string='Date de mise en service', required=True)
    methode = fields.Selection(METHODES, string="Mode d'amortissement", required=True, default='lineaire')
    duree = fields.Integer(string='Durée', required=True, default=10)
    analytic_id = fields.Many2one('account.analytic.account', string='Section analytique')
    partner_id = fields.Many2one('res.partner', string='Fournisseur')
    move_id = fields.Many2one('account.move', string="Facture d'origine", readonly=True, copy=False)
    move_line_id = fields.Many2one('account.move.line', readonly=True, copy=False)
    ref_facture = fields.Char(related='move_id.name', string="Facture d'origine")
    plan_ids = fields.One2many('ka.immo.plan', 'immo_id', string="Plan d'amortissement")
    cumul = fields.Monetary(compute='_compute_vnc', string='Amortissements cumulés', store=True)
    vnc = fields.Monetary(compute='_compute_vnc', string='Valeur nette comptable', store=True)
    cpt_immo = fields.Char(related='famille_id.cpt_immo', string='Immobilisation')
    cpt_amort = fields.Char(related='famille_id.cpt_amort', string='Amortissement cumulé')
    cpt_dotation = fields.Char(related='famille_id.cpt_dotation', string='Dotation')
    analytic_txt = fields.Char(compute='_compute_analytic_txt', string='Section analytique')
    duree_txt = fields.Char(compute='_compute_duree_txt', string='Durée')
    plan_badge = fields.Char(compute='_compute_plan_badge')
    ligne_facture = fields.Char(string='Ligne de facture', readonly=True)
    state = fields.Selection([('creation', 'En création'), ('a_confirmer', 'À confirmer'), ('en_service', 'En service'),
                              ('sortie', 'Sortie')], default='creation', string='Statut', tracking=True)
    sortie_ids = fields.One2many('ka.immo.sortie', 'immo_id')
    ka_statut_label = fields.Char(compute='_compute_statut_label', string='Statut')

    def _ka_subtitle(self):
        self.ensure_one()
        if self.state == 'creation' and not self.intitule:
            return 'Nouvelle immobilisation — bien existant ou apporté'
        origine = ' (créée depuis la facture %s)' % self.ref_facture if self.move_id else ''
        return '%s — %s%s' % (self.name, self.intitule or '', origine)

    @api.depends('plan_ids.state', 'plan_ids.dotation', 'valeur')
    def _compute_vnc(self):
        for i in self:
            cumul = sum(i.plan_ids.filtered(lambda p: p.move_id).mapped('dotation'))
            i.cumul = cumul
            i.vnc = i.valeur - cumul

    @api.depends('state')
    def _compute_statut_label(self):
        labels = dict(self._fields['state'].selection)
        for i in self:
            i.ka_statut_label = labels[i.state]

    @api.depends('duree')
    def _compute_duree_txt(self):
        for i in self:
            i.duree_txt = '%s an%s' % (i.duree, 's' if i.duree > 1 else '')

    @api.depends('analytic_id')
    def _compute_analytic_txt(self):
        for i in self:
            i.analytic_txt = '%s — %s' % (i.analytic_id.code or '', i.analytic_id.name or '') if i.analytic_id else ''

    @api.depends('plan_ids.move_id', 'plan_ids.date')
    def _compute_plan_badge(self):
        for i in self:
            faits = i.plan_ids.filtered(lambda p: p.move_id)
            i.plan_badge = ('Comptabilisé %s' % max(faits.mapped('date')).strftime('%m/%Y')) if faits else 'Prévisionnel'

    @api.onchange('famille_id')
    def _onchange_famille(self):
        f = self.famille_id
        if f:
            self.methode, self.duree = f.methode, f.duree

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.immo')
        return super().create(vals_list)

    # ---- plan d'amortissement (§ 3.2) -------------------------------------------------------------------------
    def _generer_plan(self):
        for i in self:
            if i.plan_ids.filtered('move_id'):
                raise UserError(_("Des dotations sont déjà comptabilisées : le plan ne peut plus être recalculé."))
            i.plan_ids.unlink()
            echeances = calcul_plan(i.valeur, i.date_service, i.duree, i.methode)
            i.plan_ids = [Command.create({'date': d, 'base': i.valeur, 'dotation': dot, 'cumul': cum,
                                          'vnc': i.valeur - cum}) for d, dot, cum in echeances]

    def action_calculer(self):
        for i in self:
            i._generer_plan()
            if i.state == 'creation':
                i.state = 'en_service'

    def action_confirmer(self):
        """Confirme la mise en immobilisation d'une dépense issue d'une facture fournisseur."""
        for i in self:
            if i.state != 'a_confirmer':
                raise UserError(_('Cette immobilisation est déjà confirmée.'))
            i._generer_plan()
            i.state = 'en_service'

    def action_sortie(self):
        self.ensure_one()
        s = self.env['ka.immo.sortie'].create({'immo_id': self.id})
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.immo.sortie', 'res_id': s.id, 'view_mode': 'form'}

    def action_imprimer(self):
        return self.env['ka.structure']._notif(_('Fiche immobilisation'), _('Fiche envoyée à l\'impression.'))

    def action_eclater(self):
        return self.env['ka.structure']._notif(_('Éclater la dépense'), _('Utilisez les lignes de la facture : une immobilisation est créée par ligne immobilisable.'))

    def action_open_facture(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_("Cette immobilisation n'a pas de facture d'origine."))
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': self.move_id.id, 'view_mode': 'form'}

    def action_open_plan(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.immo', 'res_id': self.id, 'view_mode': 'form',
                'views': [(self.env.ref('kode_agri_immo.view_ka_immo_plan_form').id, 'form')]}

    def action_open_fiche(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.immo', 'res_id': self.id, 'view_mode': 'form',
                'views': [(self.env.ref('kode_agri_immo.view_ka_immo_form').id, 'form')]}

    def action_open_ecritures(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Écritures', 'res_model': 'account.move',
                'view_mode': 'list,form', 'domain': [('id', 'in', self.plan_ids.move_id.ids)]}

    def action_creer(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.immo', 'view_mode': 'form',
                'views': [(self.env.ref('kode_agri_immo.view_ka_immo_manuelle_form').id, 'form')]}


class KaImmoPlan(models.Model):
    _name = 'ka.immo.plan'
    _description = "Échéance du plan d'amortissement"
    _order = 'date, id'

    immo_id = fields.Many2one('ka.immo', required=True, ondelete='cascade')
    date = fields.Date(string='Échéance', required=True)
    currency_id = fields.Many2one(related='immo_id.currency_id')
    base = fields.Monetary(string='Base')
    dotation = fields.Monetary(string='Dotation')
    cumul = fields.Monetary(string='Cumul')
    vnc = fields.Monetary(string='VNC')
    move_id = fields.Many2one('account.move', string='Pièce', readonly=True, copy=False)
    statut = fields.Selection([('comptabilisee', 'Comptabilisée'), ('a_comptabiliser', 'À comptabiliser'),
                               ('previsionnelle', 'Prévisionnelle')], compute='_compute_statut', string='Statut')

    @api.depends('move_id', 'date')
    def _compute_statut(self):
        today = fields.Date.context_today(self)
        for p in self:
            p.statut = 'comptabilisee' if p.move_id else ('a_comptabiliser' if p.date <= fin_de_mois(today) else 'previsionnelle')


class KaImmoParc(models.TransientModel):
    """Consultation du parc : indicateurs et filtres (écran 3.1d)."""
    _name = 'ka.immo.parc'
    _description = 'Immobilisations — consultation du parc'

    statut = fields.Selection([('en_service', 'En service'), ('sortie', 'Sortie'), ('tous', 'Tous')], string='Statut', default='en_service')
    famille_id = fields.Many2one('ka.immo.famille', string='Famille')
    site_id = fields.Many2one('ka.site', string='Site')
    regroupement = fields.Selection([('famille', 'Famille'), ('site', 'Site')], string='Regroupement', default='famille')
    immo_ids = fields.Many2many('ka.immo', compute='_compute_immos', string='Immobilisations')
    nb_service = fields.Integer(compute='_compute_kpi', string='En service')
    valeur_brute = fields.Float(compute='_compute_kpi', string='Valeur brute', digits=(16, 0))
    vnc = fields.Float(compute='_compute_kpi', string='Valeur nette comptable', digits=(16, 0))
    nb_sorties = fields.Integer(compute='_compute_kpi', string="Sorties de l'année")
    brute_txt = fields.Char(compute='_compute_kpi', string='Valeur brute')
    vnc_txt = fields.Char(compute='_compute_kpi', string='Valeur nette comptable')

    @api.depends('statut', 'famille_id', 'site_id', 'regroupement')
    def _compute_immos(self):
        for p in self:
            dom = []
            if p.statut and p.statut != 'tous':
                dom.append(('state', '=', p.statut))
            if p.famille_id:
                dom.append(('famille_id', '=', p.famille_id.id))
            if p.site_id:
                dom.append(('site_id', '=', p.site_id.id))
            order = 'famille_id, name' if p.regroupement == 'famille' else 'site_id, name'
            p.immo_ids = self.env['ka.immo'].search(dom, order=order)

    def _compute_kpi(self):
        Immo = self.env['ka.immo']
        debut = fields.Date.today().replace(month=1, day=1)
        def md(x):
            return '%s Md FCFA' % ('%.2f' % (x / 1e9)).replace('.', ',') if x >= 1e9 else '{:,.0f} FCFA'.format(x).replace(',', ' ')
        for p in self:
            service = Immo.search([('state', '=', 'en_service')])
            p.nb_service = len(service)
            p.valeur_brute, p.vnc = sum(service.mapped('valeur')), sum(service.mapped('vnc'))
            p.brute_txt, p.vnc_txt = md(p.valeur_brute), md(p.vnc)
            p.nb_sorties = self.env['ka.immo.sortie'].search_count([('state', '=', 'validee'), ('date', '>=', debut)])

    def action_filtrer(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form'}

    def action_exporter(self):
        return self.env['ka.structure']._notif(_('Export'), _('État du parc exporté.'))

    def action_imprimer(self):
        return self.env['ka.structure']._notif(_("État du parc"), _("État du parc envoyé à l'impression."))
