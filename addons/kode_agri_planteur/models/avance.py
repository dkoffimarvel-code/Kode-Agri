from odoo import _, api, fields, models
from odoo.exceptions import UserError


class KaAvanceRegle(models.Model):
    _name = 'ka.avance.regle'
    _description = "Règle de récupération d'avance"

    name = fields.Char(string='Règle', required=True)
    mode = fields.Selection([('total', '100 % sur le prochain décompte'), ('taux', 'Taux fixe'),
                             ('echeancier', 'Échéancier'), ('plafond', 'Plafond par décompte')],
                            default='taux', required=True)
    taux = fields.Float(string='Taux (%)')


class KaAvance(models.Model):
    _name = 'ka.avance'
    _description = "Demande d'avance de campagne"
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° avance', readonly=True, copy=False, default='Nouveau')
    partner_id = fields.Many2one('res.partner', string='Fournisseur', required=True,
                                 domain=[('ka_categorie', '=', 'planteur_coop')])
    nature = fields.Selection([('numeraire', 'Numéraire (préfinancement)'),
                               ('intrants', 'Intrants'), ('materiel', 'Matériel')],
                              string="Nature d'avance", required=True, default='numeraire')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    amount = fields.Monetary(string='Montant', required=True)
    date_octroi = fields.Date(string="Date d'octroi", default=fields.Date.context_today)
    regle_id = fields.Many2one('ka.avance.regle', string='Règle de récupération', required=True)
    plafond = fields.Monetary(string='Plafond par période')
    collectif = fields.Char(string='Collectif', default='Avances aux planteurs', readonly=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Site')
    recupere = fields.Monetary(string='Récupéré', readonly=True)
    state = fields.Selection([
        ('brouillon', 'Brouillon'), ('soumise', 'À approuver'), ('approuvee', 'Approuvée'),
        ('versee', 'Versée'), ('recuperee', 'Récupérée'), ('refusee', 'Refusée'),
    ], default='brouillon', string='Statut', tracking=True)
    signature_ids = fields.One2many('ka.avance.signature', 'avance_id', string='Circuit de signature')
    info = fields.Char(compute='_compute_info')
    validation_txt = fields.Char(string='Validation / Approbation', compute='_compute_validation_txt')

    def _ka_subtitle(self):
        self.ensure_one()
        return "Demande d'avance de campagne"

    @api.depends('name', 'partner_id.name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = ' — '.join(x for x in (rec.name, rec.partner_id.name) if x)

    @api.depends('state', 'signature_ids.statut', 'signature_ids.signataire', 'warehouse_id', 'collectif')
    def _compute_validation_txt(self):
        for rec in self:
            sig = {s.etape: s.signataire or '' for s in rec.signature_ids}
            agent = sig.get('Soumission', 'Agent collecte')
            if rec.warehouse_id:
                agent = '%s (%s)' % (agent, rec.warehouse_id.name)
            resp, treso = sig.get('Approbation', ''), sig.get('Versement', '')
            if rec.state == 'brouillon':
                txt = _("À soumettre par : %(a)s · Approbation : %(r)s.", a=agent, r=resp)
            elif rec.state == 'soumise':
                txt = _("Soumis par : %(a)s · En attente d'approbation : %(r)s.", a=agent, r=resp)
            elif rec.state == 'approuvee':
                txt = _("Approuvée par : %(r)s · En attente de versement : %(t)s.", r=resp, t=treso)
            elif rec.state == 'refusee':
                txt = _("Refusée par : %(r)s.", r=resp)
            else:
                txt = _("Approuvée par : %(r)s · Versée par : %(t)s.", r=resp, t=treso)
            rec.validation_txt = '%s %s' % (txt, _("Imputation : compte de tiers « %s ».") % (rec.collectif or ''))

    @api.depends('partner_id.ka_solde_avance', 'plafond', 'amount', 'state')
    def _compute_info(self):
        for rec in self:
            solde = rec.partner_id.ka_solde_avance
            fmt = '{:,.0f}'.format(solde).replace(',', ' ')
            if rec.plafond and solde + (rec.amount if rec.state in ('brouillon', 'soumise') else 0) > rec.plafond:
                rec.info = _("Solde d'avance en cours : %s FCFA — encours planteur au-delà du plafond autorisé.") % fmt
            else:
                rec.info = _("Solde d'avance en cours : %s FCFA — encours planteur sous le plafond autorisé.") % fmt

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.avance')
        recs = super().create(vals_list)
        for rec in recs:
            rec._init_circuit()
        return recs

    def _init_circuit(self):
        self.signature_ids = [(0, 0, {'etape': 'Soumission', 'signataire': 'Agent collecte', 'statut': 'attente'}),
                              (0, 0, {'etape': 'Approbation', 'signataire': 'Responsable collecte', 'statut': 'avenir'}),
                              (0, 0, {'etape': 'Versement', 'signataire': 'Trésorerie (règlement de type avance)',
                                      'statut': 'avenir'})]

    def _set_step(self, etape, statut):
        for sig in self.signature_ids.filtered(lambda s: s.etape == etape):
            sig.write({'statut': statut, 'date': fields.Date.context_today(self) if statut == 'fait' else False})

    def action_soumettre(self):
        for rec in self:
            if rec.state != 'brouillon':
                raise UserError(_('Seule une avance en brouillon peut être soumise.'))
            rec._set_step('Soumission', 'fait')
            rec._set_step('Approbation', 'attente')
            rec.state = 'soumise'

    def action_approuver(self):
        self._set_step('Approbation', 'fait')
        self._set_step('Versement', 'attente')
        self.write({'state': 'approuvee'})

    def action_refuser(self):
        self.write({'state': 'refusee'})

    def action_verser(self):
        self._set_step('Versement', 'fait')
        self.write({'state': 'versee'})

    def action_open_compte(self):
        return self.partner_id.action_open_compte_courant()


class KaAvanceSignature(models.Model):
    _name = 'ka.avance.signature'
    _description = "Étape du circuit de signature d'une avance"
    _order = 'id'

    avance_id = fields.Many2one('ka.avance', required=True, ondelete='cascade')
    etape = fields.Char(string='Étape')
    signataire = fields.Char(string='Signataire')
    statut = fields.Selection([('fait', 'Fait'), ('attente', 'En attente'), ('avenir', 'À venir')],
                              string='Statut')
    date = fields.Date()
