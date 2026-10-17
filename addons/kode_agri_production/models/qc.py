from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import TRACABILITE, ka_param


class KaContaminantType(models.Model):
    _name = 'ka.contaminant.type'
    _description = 'Type de contaminant'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)


# --- 4.3.1 Contrôle à la réception de fond de tasse (non bloquant) -----------------------------------
class KaQcReception(models.Model):
    _name = 'ka.qc.reception'
    _description = 'Contrôle réception — contaminants'
    _inherit = ['ka.document']
    _order = 'name desc'

    name = fields.Char(string='N° contrôle', readonly=True, copy=False, default='Nouveau')
    ticket_id = fields.Many2one('ka.ticket', string='Ticket de pesée', required=True, ondelete='cascade')
    partner_id = fields.Many2one(related='ticket_id.partner_id', string='Fournisseur')
    date_reception = fields.Date(related='ticket_id.date_pesee', string='Date de réception')
    ticket_name = fields.Char(related='ticket_id.name', string='N° ticket')
    transport = fields.Char(related='ticket_id.ka_transport', string='Transport')
    poids1 = fields.Float(related='ticket_id.ka_poids1', string='Poids 1', digits=(8, 0))
    poids2 = fields.Float(related='ticket_id.ka_poids2', string='Poids 2', digits=(8, 0))
    poids_net = fields.Float(related='ticket_id.poids_net', string='Poids net humide', digits=(8, 0))
    tracabilite = fields.Selection(TRACABILITE, string='Statut de traçabilité', default='eudr')
    line_ids = fields.One2many('ka.qc.reception.line', 'qc_id', string='Poids des contaminants')
    total = fields.Float(compute='_compute_total', string='Total contaminants', digits=(8, 1))
    taux = fields.Float(compute='_compute_total', string='Taux de contaminants', digits=(6, 2))
    controleur_id = fields.Many2one('res.users', string='Contrôleur', default=lambda s: s.env.user)
    date_heure = fields.Datetime(string='Date et heure', default=fields.Datetime.now)
    state = fields.Selection([('brouillon', 'Non bloquant'), ('valide', 'Validé')], default='brouillon', string='Statut')

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — ticket %s' % (self.name, self.ticket_name or '')

    @api.depends('line_ids.poids', 'poids_net')
    def _compute_total(self):
        for q in self:
            q.total = sum(q.line_ids.mapped('poids'))
            q.taux = (q.total / q.poids_net * 100.0) if q.poids_net else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        types = self.env['ka.contaminant.type'].search([])
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.qc.reception')
            if not vals.get('line_ids'):
                vals['line_ids'] = [Command.create({'type_id': t.id}) for t in types]
        return super().create(vals_list)

    def action_valider(self):
        self.write({'state': 'valide'})


class KaQcReceptionLine(models.Model):
    _name = 'ka.qc.reception.line'
    _description = 'Poids de contaminant'

    qc_id = fields.Many2one('ka.qc.reception', required=True, ondelete='cascade')
    type_id = fields.Many2one('ka.contaminant.type', string='Type de contaminant', required=True)
    poids = fields.Float(string='Poids (kg)', digits=(8, 1))


# --- 4.3.2 Essai DRC (rattaché à un lot) ----------------------------------------------------------------
class KaDrcEssai(models.Model):
    _name = 'ka.drc.essai'
    _description = 'Essai DRC'
    _inherit = ['ka.document']
    _order = 'name desc'

    name = fields.Char(string='N° essai', readonly=True, copy=False, default='Nouveau')
    lot_id = fields.Many2one('stock.lot', string='Lot', required=True)
    poids_lot = fields.Float(related='lot_id.product_qty', string='Poids du lot à date', digits=(10, 0))
    statut_lot = fields.Char(string='Statut du lot', default='En constitution')
    tracabilite = fields.Selection(related='lot_id.ka_tracabilite', string='Statut de traçabilité')
    date = fields.Date(string="Date de l'essai", default=fields.Date.context_today)
    methode = fields.Selection([('acide', "Coagulation à l'acide formique"), ('etuve', 'Étuvage')],
                               string='Méthode', default='acide')
    laborantin_id = fields.Many2one('res.users', string='Laborantin', default=lambda s: s.env.user)
    echantillon_g = fields.Float(string='Échantillon prélevé', digits=(8, 0), default=500)
    poids_sec_g = fields.Float(string='Poids sec après séchage', digits=(8, 0))
    drc = fields.Float(string='DRC mesuré', compute='_compute_drc', store=True, digits=(5, 1))
    drc_ref = fields.Float(string='DRC de référence', digits=(5, 0),
                           default=lambda s: ka_param(s.env, 'drc_reference', 60.0))
    ecart = fields.Float(string='Écart', compute='_compute_drc', store=True, digits=(5, 1))
    drc_lot = fields.Float(related='lot_id.ka_drc', string='Titre du lot après mise à jour', digits=(5, 1))
    rang = fields.Integer(compute='_compute_rang')
    state = fields.Selection([('brouillon', 'Brouillon'), ('conforme', 'Conforme'), ('ecart', 'Écart à analyser')],
                             default='brouillon', string='Statut')

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — lot %s · %de essai sur ce lot' % (self.name, self.lot_id.name or '', self.rang)

    @api.depends('echantillon_g', 'poids_sec_g', 'drc_ref')
    def _compute_drc(self):
        for e in self:
            e.drc = (e.poids_sec_g / e.echantillon_g * 100.0) if e.echantillon_g else 0.0
            e.ecart = e.drc - e.drc_ref if e.drc else 0.0

    @api.depends('lot_id')
    def _compute_rang(self):
        for e in self:
            e.rang = self.search_count([('lot_id', '=', e.lot_id.id), ('id', '<=', e._origin.id or 0)]) or 1 \
                if e.lot_id else 1

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.drc.essai')
        return super().create(vals_list)

    def action_enregistrer(self):
        tol = ka_param(self.env, 'drc_tolerance', 5.0)
        for e in self:
            e.state = 'conforme' if abs(e.ecart) <= tol else 'ecart'

    def action_maj_titre(self):
        for e in self:
            if e.state == 'brouillon':
                e.action_enregistrer()
            e.lot_id.ka_set_drc(round(e.drc, 2), _('Essai %s') % e.name)

    def action_historique(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Historique des essais', 'res_model': 'ka.drc.essai',
                'view_mode': 'list,form', 'domain': [('lot_id', '=', self.lot_id.id)]}


# --- 4.3.3 Test de granulés --------------------------------------------------------------------------------
class KaQcGranul(models.Model):
    _name = 'ka.qc.granul'
    _description = 'Contrôle granulation'
    _inherit = ['ka.document']
    _order = 'name desc'

    name = fields.Char(string='N° contrôle', readonly=True, copy=False, default='Nouveau')
    of_id = fields.Many2one('ka.of', string='OF', required=True)
    poste_id = fields.Many2one('mrp.workcenter', string='Poste de charge')
    centre = fields.Char(string='Centre de charge', default='CC02 — Zone humide', readonly=True)
    date_heure = fields.Datetime(string='Date et heure', default=fields.Datetime.now)
    granulo_cible = fields.Char(string='Granulométrie cible', default='4 – 8 mm', readonly=True)
    granulo_mesuree = fields.Char(string='Granulométrie mesurée')
    homogeneite = fields.Selection([('homogene', 'Homogène'), ('heterogene', 'Hétérogène')], string='Homogénéité')
    corps_etrangers = fields.Selection([('aucun', 'Aucun'), ('presents', 'Présents')], string='Corps étrangers')
    resultat = fields.Selection([('conforme', 'Conforme'), ('non_conforme', 'Non conforme')], compute='_compute_res',
                                store=True, string='Résultat')
    controleur_id = fields.Many2one('res.users', string='Contrôleur', default=lambda s: s.env.user)
    tracabilite = fields.Selection(related='of_id.tracabilite', string='Statut de traçabilité')

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — poste %s · OF %s' % (self.name, self.poste_id.display_name or '', self.of_id.name or '')

    @api.depends('homogeneite', 'corps_etrangers')
    def _compute_res(self):
        for q in self:
            q.resultat = 'conforme' if q.homogeneite == 'homogene' and q.corps_etrangers == 'aucun' else 'non_conforme'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.qc.granul')
        return super().create(vals_list)

    def action_valider(self):
        """Non bloquant : un résultat non conforme n'interdit pas le passage au séchoir."""
        return True


# --- 4.3.4 Contrôle panier (P0 / PRI), sans impact stock --------------------------------------------------------
class KaQcPanier(models.Model):
    _name = 'ka.qc.panier'
    _description = 'Contrôle panier — P0 / PRI'
    _inherit = ['ka.document']
    _order = 'id desc'

    name = fields.Char(string='N° contrôle', readonly=True, copy=False, default='Nouveau')
    panier_id = fields.Many2one('ka.panier', string='Panier', required=True, ondelete='cascade')
    sechoir_id = fields.Many2one(related='panier_id.sechoir_id', string='Séchoir')
    heure = fields.Float(string='Heure de prélèvement', default=16.0)
    laborantin_id = fields.Many2one('res.users', string='Laborantin', default=lambda s: s.env.user)
    p0 = fields.Float(string='P0 mesuré', digits=(5, 0))
    pri = fields.Float(string='PRI mesuré', digits=(5, 0))
    grade_vise = fields.Selection(related='panier_id.of_id.grade_vise', string='Grade visé (OF)')
    resultat = fields.Selection([('conforme', 'Conforme'), ('non_conforme', 'Non conforme'), ('a_saisir', 'À saisir')],
                                compute='_compute_res', string='Résultat')
    state = fields.Selection([('brouillon', 'Sans impact stock'), ('valide', 'Validé')], default='brouillon',
                             string='Statut')

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — séchoir %s · OF %s' % (self.name, self.sechoir_id.name or '', self.panier_id.of_id.name or '')

    @api.depends('p0', 'pri', 'grade_vise')
    def _compute_res(self):
        grade = self.env['ka.grade'].search([('code', '=', 'TSR10')], limit=1)
        for q in self:
            if not (q.p0 and q.pri):
                q.resultat = 'a_saisir'
            else:
                q.resultat = 'conforme' if grade.verifie({'p0': q.p0, 'pri': q.pri, 'ml': 1}) else 'non_conforme'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.qc.panier')
        return super().create(vals_list)

    def action_valider(self):
        """RG-4.5 : aucun impact sur les stocks ; la production est notifiée (action automatisée)."""
        for q in self:
            if not (q.p0 and q.pri):
                raise UserError(_('Saisissez les valeurs P0 et PRI.'))
            q.state = 'valide'
            q.panier_id.message_post(body=_('Résultats P0 / PRI disponibles : %d / %d (%s).') % (
                q.p0, q.pri, dict(q._fields['resultat'].selection)[q.resultat]))
            q.panier_id.of_id.activity_schedule(
                'mail.mail_activity_data_todo', summary=_('Résultats panier %s disponibles') % q.panier_id.chrono,
                user_id=q.panier_id.user_id.id or self.env.uid)


# --- 4.3.5 Contrôle à libération (équivalent conteneur) -----------------------------------------------------------
class KaQcLiberation(models.Model):
    _name = 'ka.qc.liberation'
    _description = 'Contrôle à libération — équivalent conteneur'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° contrôle', readonly=True, copy=False, default='Nouveau')
    line_ids = fields.One2many('ka.qc.liberation.line', 'qc_id', string='Colis')
    controleur_id = fields.Many2one('res.users', string='Contrôleur', default=lambda s: s.env.user)
    nb_colis = fields.Integer(compute='_compute_info')
    poids = fields.Float(compute='_compute_info', digits=(10, 0))
    nb_bloques = fields.Integer(compute='_compute_info')
    badge_label = fields.Char(compute='_compute_info')
    state = fields.Selection([('en_cours', 'En cours'), ('libere', 'Libéré')], default='en_cours', string='Statut')

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — %s colis · %s kg · contrôleur %s' % (
            self.name, self.nb_colis, ('{:,.0f}'.format(self.poids)).replace(',', ' '), self.controleur_id.name or '')

    @api.depends('line_ids.resultat', 'line_ids.lot_id')
    def _compute_info(self):
        for q in self:
            q.nb_colis = len(q.line_ids)
            q.poids = sum(q.line_ids.lot_id.mapped('product_qty'))
            q.nb_bloques = len(q.line_ids.filtered(lambda l: l.resultat == 'bloque'))
            q.badge_label = ('%s colis bloqués' % q.nb_bloques) if q.nb_bloques else (
                'Libéré' if q.state == 'libere' else 'Conforme')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.qc.liberation')
        return super().create(vals_list)

    def action_valider_selection(self):
        """Valide colis par colis les lignes cochées (conformes uniquement)."""
        for line in self.line_ids.filtered(lambda l: l.a_valider and l.resultat == 'a_controler'):
            line._liberer()
        self.line_ids.write({'a_valider': False})

    def action_valider_conteneur(self):
        """RG-4.12 : validation globale possible seulement si tous les colis sont conformes."""
        for q in self:
            if q.line_ids.filtered(lambda l: l.resultat == 'bloque'):
                raise UserError(_("Des colis bloqués doivent être remplacés par l'agent d'expédition puis recontrôlés."))
            for line in q.line_ids.filtered(lambda l: l.resultat == 'a_controler'):
                line._liberer()
            if q.line_ids and all(l.resultat == 'libere' for l in q.line_ids):
                q.state = 'libere'

    def action_bon(self):
        self.ensure_one()
        if self.state != 'libere':
            raise UserError(_("Le bon de libération n'est disponible qu'après validation du conteneur."))
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Bon de libération'), 'type': 'success', 'sticky': False,
                           'message': _('Bon de libération conteneur %s édité.') % self.name}}


class KaQcLiberationLine(models.Model):
    _name = 'ka.qc.liberation.line'
    _description = 'Colis soumis au contrôle à libération'

    qc_id = fields.Many2one('ka.qc.liberation', required=True, ondelete='cascade')
    lot_id = fields.Many2one('stock.lot', string='Lot (colis)', required=True, domain=[('ka_est_colis', '=', True)])
    statut = fields.Char(compute='_compute_vals', string='Statut')
    p0 = fields.Float(compute='_compute_vals', string='P0', digits=(5, 0))
    pri = fields.Float(compute='_compute_vals', string='PRI', digits=(5, 0))
    ml = fields.Float(compute='_compute_vals', string='ML', digits=(5, 0))
    imp = fields.Float(compute='_compute_vals', string='Impuretés', digits=(5, 2))
    azote = fields.Float(compute='_compute_vals', string='Azote', digits=(5, 2))
    cendres = fields.Float(compute='_compute_vals', string='Cendres', digits=(5, 2))
    vm = fields.Float(compute='_compute_vals', string='Mat. vol.', digits=(5, 2))
    resultat = fields.Selection([('a_controler', 'À contrôler'), ('libere', 'Libéré'),
                                 ('bloque', 'Bloqué — à remplacer')], default='a_controler', string='Résultat')
    a_valider = fields.Boolean(string='Sélection')

    @api.depends('lot_id.ka_etat', 'lot_id.ka_statut_id', 'lot_id.ka_spec_id.line_ids.resultat')
    def _compute_vals(self):
        for l in self:
            l.statut = l.lot_id.ka_etat_label()
            res = l.lot_id.ka_spec_id.ka_resultats() if l.lot_id.ka_spec_id else {}
            for t in ('p0', 'pri', 'ml', 'imp', 'azote', 'cendres', 'vm'):
                l[t] = res.get(t, 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for l in lines.filtered(lambda l: l.lot_id.ka_etat == 'Q' and l.lot_id.ka_motif):
            l.resultat = 'bloque'
        return lines

    def _liberer(self):
        for l in self:
            if l.lot_id.ka_motif:
                l.resultat = 'bloque'
                continue
            l.lot_id.ka_liberer()
            l.resultat = 'libere'
