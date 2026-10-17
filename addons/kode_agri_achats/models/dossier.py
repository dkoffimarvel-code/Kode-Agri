from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

TAUX_EUR_XOF = 655.957
CLES = [('valeur', 'Valeur FOB'), ('poids', 'Poids'), ('quantite', 'Quantité')]


class KaDossierImport(models.Model):
    """Dossier d'import : commande, frais d'approche et documents ; coût complet d'entrée en stock (§ 2.2.1)."""
    _name = 'ka.dossier.import'
    _description = "Dossier d'import"
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° dossier', readonly=True, copy=False, default='Nouveau')
    partner_id = fields.Many2one('res.partner', string='Fournisseur étranger', required=True)
    transitaire_id = fields.Many2one('res.partner', string='Transitaire', required=True,
                                     domain=[('ka_categorie', '=', 'transitaire')])
    currency_id = fields.Many2one('res.currency', string='Devise',
                                  default=lambda s: s.env.ref('base.EUR', raise_if_not_found=False))
    company_currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    cours = fields.Float(compute='_compute_cours', string='Cours', digits=(10, 3))
    commande_id = fields.Many2one('ka.commande', string="Commande d'achat")
    date_ouverture = fields.Date(string="Date d'ouverture", default=fields.Date.context_today)
    section_txt = fields.Char(string='Section analytique', default='ACHIMP (non modifiable)', readonly=True)
    site_id = fields.Many2one('ka.site', string='Site')
    line_ids = fields.One2many('ka.dossier.ligne', 'dossier_id', string='Articles importés')
    frais_ids = fields.One2many('ka.dossier.frais', 'dossier_id', string="Frais d'approche")
    cle = fields.Selection(CLES, string='Clé de répartition', default='valeur', required=True)
    ajustement = fields.Boolean(string='Ajustement de valorisation', default=True)
    nb_articles = fields.Integer(compute='_compute_totaux', string='Articles')
    nb_factures = fields.Integer(compute='_compute_totaux', string='Factures de frais')
    total_fob = fields.Monetary(compute='_compute_totaux', currency_field='company_currency_id')
    total_frais = fields.Monetary(compute='_compute_totaux', string="Total des frais d'approche", currency_field='company_currency_id')
    ventile = fields.Monetary(compute='_compute_totaux', currency_field='company_currency_id')
    a_ventiler = fields.Monetary(compute='_compute_totaux', string='Frais restant à ventiler', currency_field='company_currency_id')
    cout_complet = fields.Monetary(compute='_compute_totaux', string='Coût complet', currency_field='company_currency_id')
    factures_txt = fields.Char(compute='_compute_totaux', string='Factures de frais')
    nb_docs = fields.Integer(compute='_compute_docs')
    state = fields.Selection([('en_cours', 'En cours'), ('valide', 'Validé'), ('cloture', 'Clôturé')],
                             default='en_cours', string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — %s' % (self.name, self.partner_id.name or '')

    @api.depends('currency_id', 'company_currency_id', 'date_ouverture')
    def _compute_cours(self):
        for d in self:
            rate = 1.0
            if d.currency_id and d.currency_id != d.company_currency_id:
                rate = d.currency_id._get_conversion_rate(d.currency_id, d.company_currency_id, self.env.company,
                                                          d.date_ouverture or fields.Date.today())
                if d.currency_id.name == 'EUR' and d.company_currency_id.name == 'XOF' and abs(rate - 1.0) < 1e-6:
                    rate = TAUX_EUR_XOF
            d.cours = rate

    @api.depends('line_ids.fob', 'line_ids.frais', 'frais_ids.montant', 'frais_ids.facture_ref')
    def _compute_totaux(self):
        for d in self:
            d.nb_articles = len(d.line_ids)
            refs = {f.facture_ref for f in d.frais_ids if f.facture_ref}
            d.nb_factures = len(refs)
            d.factures_txt = '%s factures transitaire' % d.nb_factures
            d.total_fob = sum(d.line_ids.mapped('fob'))
            d.total_frais = sum(d.frais_ids.mapped('montant'))
            d.ventile = sum(d.line_ids.mapped('frais'))
            d.a_ventiler = d.total_frais - d.ventile
            d.cout_complet = d.total_fob + d.ventile

    def _compute_docs(self):
        for d in self:
            d.nb_docs = self.env['ir.attachment'].search_count([('res_model', '=', 'ka.dossier.import'), ('res_id', '=', d.id)]) if d.id else 0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.dossier.import')
        return super().create(vals_list)

    # ---- ventilation (§ 2.2.1.1) ---------------------------------------------------------------------------------
    def _base(self, line):
        return {'valeur': line.fob, 'poids': line.poids, 'quantite': line.qty}[self.cle]

    def action_ventiler(self):
        """Frais ventilés = total des frais × (base de l'article / base totale) ; la somme est toujours égale au total."""
        for d in self:
            if d.state != 'en_cours':
                raise UserError(_('Le dossier est déjà validé.'))
            total_base = sum(d._base(l) for l in d.line_ids)
            if not total_base:
                raise UserError(_("La clé de répartition « %s » ne donne aucune base de calcul.") % dict(CLES)[d.cle])
            reste = d.total_frais
            lignes = d.line_ids
            for i, l in enumerate(lignes):
                if i == len(lignes) - 1:
                    montant = reste                               # la dernière ligne absorbe l'arrondi (100 %)
                else:
                    montant = round(d.total_frais * d._base(l) / total_base)
                    reste -= montant
                l.write({'coef': d._base(l) / total_base * 100.0, 'frais': montant})

    def action_recalculer(self):
        return self.action_ventiler()

    def action_annuler_ventilation(self):
        for d in self.filtered(lambda d: d.state == 'en_cours'):
            d.line_ids.write({'coef': 0.0, 'frais': 0.0})

    def action_ouvrir_ventilation(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.dossier.import', 'res_id': self.id,
                'view_mode': 'form', 'views': [(self.env.ref('kode_agri_achats.view_ka_ventilation_form').id, 'form')]}

    def action_retour_dossier(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.dossier.import', 'res_id': self.id,
                'view_mode': 'form', 'views': [(self.env.ref('kode_agri_achats.view_ka_dossier_form').id, 'form')]}

    # ---- validation (§ 2.2.1.2) -----------------------------------------------------------------------------------
    def action_valider(self):
        """Contrôles : frais ventilés à 100 %, facture transitaire renseignée, pièces jointes, section affectée.
        Puis valorisation des articles au coût complet d'entrée."""
        for d in self:
            if abs(d.a_ventiler) > 0.5:
                raise UserError(_("Les frais ne sont pas ventilés à 100 %% (reste %s).") % round(d.a_ventiler))
            if not d.frais_ids or not all(f.facture_ref for f in d.frais_ids):
                raise UserError(_("Chaque frais d'approche doit être rattaché à une facture du transitaire."))
            if not d.nb_docs:
                raise UserError(_("Joignez au moins une pièce justificative au dossier (RG-2.2)."))
            if d.ajustement:
                for l in d.line_ids.filtered(lambda l: l.qty):
                    l.product_id.standard_price = l.cout_complet / l.qty
            d.state = 'valide'

    def action_cloturer(self):
        self.filtered(lambda d: d.state == 'valide').write({'state': 'cloture'})

    def action_joindre(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Joindre un document', 'res_model': 'ir.attachment',
                'view_mode': 'form', 'target': 'new',
                'context': {'default_res_model': 'ka.dossier.import', 'default_res_id': self.id}}

    def action_imprimer(self):
        return self.env['ka.structure']._notif(_("Dossier d'import"), _('Dossier envoyé à l\'impression.'))

    def action_open_commande(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.commande', 'res_id': self.commande_id.id,
                'view_mode': 'form'}

    def action_open_factures(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Factures', 'res_model': 'ka.dossier.frais',
                'view_mode': 'list', 'domain': [('dossier_id', '=', self.id)]}


class KaDossierLigne(models.Model):
    _name = 'ka.dossier.ligne'
    _description = "Article importé"
    _order = 'id'

    dossier_id = fields.Many2one('ka.dossier.import', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Article', required=True)
    qty = fields.Float(string='Quantité', digits=(12, 0))
    uom_id = fields.Many2one(related='product_id.uom_id', string='Unité')
    poids = fields.Float(string='Poids (kg)', digits=(12, 0))
    currency_id = fields.Many2one(related='dossier_id.company_currency_id')
    fob = fields.Monetary(string='Valeur FOB (XOF)')
    coef = fields.Float(string='Coefficient', digits=(6, 1))
    frais = fields.Monetary(string='Frais ventilés')
    cout_complet = fields.Monetary(compute='_compute_cout', string="Coût complet d'entrée", store=True)

    @api.depends('fob', 'frais')
    def _compute_cout(self):
        for l in self:
            l.cout_complet = l.fob + l.frais


class KaDossierFrais(models.Model):
    _name = 'ka.dossier.frais'
    _description = "Frais d'approche"
    _order = 'id'

    dossier_id = fields.Many2one('ka.dossier.import', required=True, ondelete='cascade')
    type = fields.Selection([('transport', 'Transport'), ('douane', 'Douane'), ('assurance', 'Assurance'),
                             ('autre', 'Autre')], string='Nature', required=True, default='transport')
    libelle = fields.Char(string='Libellé')
    facture_ref = fields.Char(string='Facture du transitaire')
    currency_id = fields.Many2one(related='dossier_id.company_currency_id')
    montant = fields.Monetary(string='Montant (XOF)')


class KaDossierListe(models.TransientModel):
    """Liste de suivi des dossiers d'import : indicateurs et filtres (écran 2.9)."""
    _name = 'ka.dossier.liste'
    _description = "Dossiers d'import — liste de suivi"

    statut = fields.Selection([('tous', 'Tous'), ('en_cours', 'En cours'), ('valide', 'Validé'), ('cloture', 'Clôturé')],
                              string='Statut', default='tous')
    transitaire_id = fields.Many2one('res.partner', string='Transitaire')
    periode = fields.Date(string='Période', help='Un jour du mois recherché')
    regroupement = fields.Selection([('statut', 'Statut'), ('transitaire', 'Transitaire')], string='Regroupement',
                                    default='statut')
    dossier_ids = fields.Many2many('ka.dossier.import', compute='_compute_dossiers', string='Dossiers')
    nb_en_cours = fields.Integer(compute='_compute_kpi', string='En cours')
    nb_valides = fields.Integer(compute='_compute_kpi', string='Validés')
    nb_clotures = fields.Integer(compute='_compute_kpi', string='Clôturés ce mois')
    a_ventiler = fields.Float(compute='_compute_kpi', string='Frais à ventiler', digits=(14, 0))

    @api.depends('statut', 'transitaire_id', 'periode')
    def _compute_dossiers(self):
        for l in self:
            dom = []
            if l.statut and l.statut != 'tous':
                dom.append(('state', '=', l.statut))
            if l.transitaire_id:
                dom.append(('transitaire_id', '=', l.transitaire_id.id))
            if l.periode:
                debut = l.periode.replace(day=1)
                dom += [('date_ouverture', '>=', debut), ('date_ouverture', '<', debut + relativedelta(months=1))]
            l.dossier_ids = self.env['ka.dossier.import'].search(dom, order='name desc')

    def _compute_kpi(self):
        D = self.env['ka.dossier.import']
        today = fields.Date.today()
        for l in self:
            l.nb_en_cours = D.search_count([('state', '=', 'en_cours')])
            l.nb_valides = D.search_count([('state', '=', 'valide')])
            l.nb_clotures = D.search_count([('state', '=', 'cloture'), ('date_ouverture', '>=', today.replace(day=1))])
            l.a_ventiler = sum(D.search([('state', '=', 'en_cours')]).mapped('a_ventiler'))

    def action_creer(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.dossier.import', 'view_mode': 'form',
                'views': [(self.env.ref('kode_agri_achats.view_ka_dossier_form').id, 'form')]}

    def action_filtrer(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'target': 'current'}

    def action_exporter(self):
        return self.env['ka.structure']._notif(_('Export'), _('Liste exportée.'))
