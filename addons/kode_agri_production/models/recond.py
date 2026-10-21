from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import TESTS, TEXTURES


class KaRecond(models.Model):
    """Ordre de qualité de reconditionnement : texture ou spécifications (§ 4.2.6)."""
    _name = 'ka.recond'
    _description = 'Ordre de reconditionnement'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° ordre', readonly=True, copy=False, default='Nouveau')
    type = fields.Selection([('texture', 'Texture'), ('specs', 'Spécifications')], required=True, default='texture')
    lot_id = fields.Many2one('stock.lot', string='Lot (colis)', required=True, domain=[('ka_est_colis', '=', True)])
    product_id = fields.Many2one(related='lot_id.product_id', string='Article')
    qty = fields.Float(related='lot_id.product_qty', string='Quantité', digits=(8, 0))
    statut_label = fields.Char(compute='_compute_statut_label', string='Statut actuel')
    motif = fields.Char(related='lot_id.ka_motif', string='Motif de déclassement')
    tracabilite = fields.Selection(related='lot_id.ka_tracabilite', string='Statut de traçabilité')
    # texture
    action_menee = fields.Char(string='Action menée')
    controleur_id = fields.Many2one('res.users', string='Contrôleur qualité', default=lambda s: s.env.user)
    recontrole = fields.Selection(TEXTURES, string='Recontrôle texture')
    date_controle = fields.Date(string='Date de contrôle', default=fields.Date.context_today)
    statut_apres = fields.Char(string='Statut après validation', compute='_compute_apres')
    motif_apres = fields.Char(string='Motif de déclassement', compute='_compute_apres')
    article_apres = fields.Char(string='Article', compute='_compute_apres')
    sortie_quarantaine = fields.Boolean(string='Sortie de quarantaine', compute='_compute_apres')
    # spécifications
    line_ids = fields.One2many('ka.recond.line', 'recond_id', string="Résultats d'analyse")
    grade_id = fields.Many2one('ka.grade', string='Grade déterminé', compute='_compute_grade')
    grade_label = fields.Char(compute='_compute_grade')
    nouvel_article_id = fields.Many2one('product.product', string='Nouvel article', compute='_compute_grade')
    of_reclassement_id = fields.Many2one('ka.of', string='OF de reclassement', readonly=True, copy=False)
    rang = fields.Integer(compute='_compute_rang')
    state = fields.Selection([('a_valider', 'À valider'), ('valide', 'Validé')], default='a_valider',
                             string='Statut', tracking=True)
    ka_etape = fields.Selection([('brouillon', 'Brouillon'), ('quarantaine', 'En quarantaine'),
                                 ('a_valider', 'À valider'), ('valide', 'Validé')],
                                string='Étape', compute='_compute_ka_etape')
    titre_label = fields.Char(compute='_compute_ka_etape', string='Libellé du titre')
    rang_label = fields.Char(compute='_compute_rang', string='Rang du reconditionnement')
    statut_colis = fields.Char(compute='_compute_statut_label', string='Statut colis')
    motif_initial = fields.Char(string='Motif initial', readonly=True, copy=False,
                                help='Motif de déclassement du colis à la création de l\'ordre (historisé).')
    code_article = fields.Char(related='lot_id.product_id.default_code', string='Code article')
    article_initial = fields.Char(string='Article initial', readonly=True, copy=False,
                                  help="Code article du colis à la création de l'ordre (historisé).")
    ka_valid_txt = fields.Char(compute='_compute_ka_valid_txt', string='Validation')
    # spécifications présentées champ par champ (écran 4.6b) : anciennes (historisées) et nouvelles
    a_p0 = fields.Float(string='P0', compute='_compute_specs', digits=(8, 0))
    a_pri = fields.Float(string='PRI', compute='_compute_specs', digits=(8, 0))
    a_ml = fields.Float(string='Viscosité Mooney (ML)', compute='_compute_specs', digits=(8, 0))
    a_imp = fields.Float(string='Impuretés', compute='_compute_specs', digits=(8, 2))
    a_azote = fields.Float(string='Azote', compute='_compute_specs', digits=(8, 2))
    a_cendres = fields.Float(string='Cendres', compute='_compute_specs', digits=(8, 2))
    a_vm = fields.Float(string='Matière volatile', compute='_compute_specs', digits=(8, 2))
    n_p0 = fields.Float(string='P0', compute='_compute_specs', inverse='_inverse_specs', digits=(8, 0))
    n_pri = fields.Float(string='PRI', compute='_compute_specs', inverse='_inverse_specs', digits=(8, 0))
    n_ml = fields.Float(string='Viscosité Mooney (ML)', compute='_compute_specs', inverse='_inverse_specs', digits=(8, 0))
    n_imp = fields.Float(string='Impuretés', compute='_compute_specs', inverse='_inverse_specs', digits=(8, 2))
    n_azote = fields.Float(string='Azote', compute='_compute_specs', inverse='_inverse_specs', digits=(8, 2))
    n_cendres = fields.Float(string='Cendres', compute='_compute_specs', inverse='_inverse_specs', digits=(8, 2))
    n_vm = fields.Float(string='Matière volatile', compute='_compute_specs', inverse='_inverse_specs', digits=(8, 2))

    @api.depends('type', 'state')
    def _compute_ka_etape(self):
        for r in self:
            if r.state == 'valide':
                r.ka_etape = 'valide'
            else:
                r.ka_etape = 'quarantaine' if r.type == 'texture' else 'a_valider'
            r.titre_label = 'Ordre de qualité — Reconditionnement %s' % (
                'texture' if r.type == 'texture' else 'spécifications')

    @api.depends('line_ids.ancien', 'line_ids.nouveau', 'line_ids.test')
    def _compute_specs(self):
        for r in self:
            par_test = {l.test: l for l in r.line_ids}
            for t, _label in TESTS:
                r['a_%s' % t] = par_test[t].ancien if t in par_test else 0.0
                r['n_%s' % t] = par_test[t].nouveau if t in par_test else 0.0

    def _inverse_specs(self):
        for r in self:
            par_test = {l.test: l for l in r.line_ids}
            cmds = []
            for t, _label in TESTS:
                valeur = r['n_%s' % t]
                if t in par_test:
                    if par_test[t].nouveau != valeur:
                        cmds.append(Command.update(par_test[t].id, {'nouveau': valeur}))
                elif valeur:
                    cmds.append(Command.create({'test': t, 'nouveau': valeur}))
            if cmds:
                r.line_ids = cmds

    @api.depends('type', 'lot_id', 'state', 'grade_id', 'motif_initial', 'article_initial')
    def _compute_ka_valid_txt(self):
        for r in self:
            lot = r.lot_id.name or ''
            code = r.article_initial or r.lot_id.product_id.default_code or r.lot_id.product_id.name or ''
            if r.type == 'texture':
                r.ka_valid_txt = ("La validation de l'ordre de reconditionnement lève le motif de déclassement et sort "
                                  "le colis %s de la quarantaine. Le colis conserve son code article (%s) : seul son "
                                  "statut change, de « %s — %s » à « %s — %s ». Même numéro de série, traçabilité "
                                  "conservée.") % (lot, code, code, r.statut_colis or r.motif_initial or '', code,
                                                   r.statut_apres or '')
            else:
                nouveau = r.grade_id.code or r.nouvel_article_id.default_code or '…'
                r.ka_valid_txt = ("La validation met à jour la fiche colis %s avec les nouvelles spécifications, "
                                  "historise les anciennes valeurs et effectue un ajustement négatif de l'article "
                                  "initial (%s) et un ajustement positif du nouvel article (%s). Un colis peut faire "
                                  "l'objet de plusieurs reconditionnements successifs. Le changement de code article "
                                  "s'effectue avec le même numéro de série : la traçabilité au lot de fond de tasse "
                                  "d'origine est conservée.") % (lot, code, nouveau)

    def _ka_subtitle(self):
        self.ensure_one()
        if self.type == 'texture':
            return 'Type : défaut de texture colis'
        return 'Type : ressaisie des spécifications colis'

    @api.depends('lot_id')
    def _compute_rang(self):
        for r in self:
            r.rang = self.search_count([('lot_id.name', '=', r.lot_id.name), ('type', '=', 'specs'),
                                        ('state', '=', 'valide')]) + 1 if r.lot_id else 1
            r.rang_label = '%d%s reconditionnement de ce colis' % (r.rang, 'er' if r.rang == 1 else 'ᵉ')

    @api.depends('lot_id.ka_etat', 'lot_id.ka_statut_id')
    def _compute_statut_label(self):
        for r in self:
            r.statut_label = r.lot_id.ka_etat_label() if r.lot_id else ''
            r.statut_colis = r.lot_id.ka_statut_id.name or ''

    @api.depends('lot_id', 'state', 'type', 'motif_initial')
    def _compute_apres(self):
        Statut = self.env['ka.statut.colis']
        for r in self:
            code = r.lot_id.product_id.default_code or ''
            statut = Statut.search([('article_code', '=', code), ('defaut', '=', False)], limit=1) if code else Statut
            r.statut_apres = statut.name or 'A — Accepté'
            r.motif_apres = r.motif_initial or r.motif or ''
            r.article_apres = code or (r.lot_id.product_id.display_name or '')
            r.sortie_quarantaine = True

    @api.depends('line_ids.nouveau')
    def _compute_grade(self):
        grades = self.env['ka.grade'].search([], order='sequence, id')
        for r in self:
            res = {l.test: l.nouveau for l in r.line_ids}
            grade = False
            if any(res.values()):
                for g in grades.filtered(lambda g: not g.hors_specs):
                    if g.verifie(res):
                        grade = g
                        break
                grade = grade or grades.filtered('hors_specs')[:1]
            r.grade_id = grade
            r.grade_label = ('%s — Standard' % grade.code) if grade and not grade.hors_specs else (grade.code or '')
            r.nouvel_article_id = grade.product_id if grade else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.recond')
            if vals.get('lot_id') and not vals.get('motif_initial'):
                vals['motif_initial'] = self.env['stock.lot'].browse(vals['lot_id']).ka_motif or False
            if vals.get('lot_id') and not vals.get('article_initial'):
                vals['article_initial'] = self.env['stock.lot'].browse(vals['lot_id']).product_id.default_code or False
        recs = super().create(vals_list)
        for r in recs.filtered(lambda r: r.type == 'specs' and not r.line_ids):
            ancien = r.lot_id.ka_spec_id.ka_resultats() if r.lot_id.ka_spec_id else {}
            r.line_ids = [Command.create({'test': t, 'ancien': ancien.get(t, 0.0)}) for t, _l in TESTS]
        return recs

    def action_valider(self):
        for r in self:
            if r.state != 'a_valider':
                continue
            lot = r.lot_id
            if r.type == 'texture':
                if r.recontrole != 'conforme':
                    raise UserError(_('Le recontrôle de texture doit être conforme pour lever le motif.'))
                statut = self.env['ka.statut.colis'].search([('article_code', '=', lot.product_id.default_code),
                                                             ('defaut', '=', False)], limit=1)
                # RG-4.11 : le colis conserve son code article, seul son statut change.
                lot.write({'ka_etat': 'A', 'ka_motif': False, 'ka_statut_id': statut.id or lot.ka_statut_id.id})
            else:
                if not r.grade_id:
                    raise UserError(_('Saisissez les nouveaux résultats avant de valider.'))
                spec = lot.ka_spec_id
                if spec:
                    self.env['ka.spec.histo'].create({
                        'lot_name': lot.name, 'recond_id': r.id,
                        'valeurs': ', '.join('%s=%s' % (l.test, l.ancien) for l in r.line_ids)})
                new_lot, of = lot.ka_reclasser(r.grade_id.product_id, r.name)
                new_spec = self.env['ka.spec'].create({
                    'lot_id': new_lot.id, 'state': 'specifie',
                    'line_ids': [Command.create({'test': l.test, 'resultat': l.nouveau}) for l in r.line_ids]})
                new_lot.ka_spec_id = new_spec
                r.write({'lot_id': new_lot.id, 'of_reclassement_id': of.id})
            r.state = 'valide'

    def action_historique(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Historique des résultats', 'res_model': 'ka.spec.histo',
                'view_mode': 'list', 'domain': [('lot_name', '=', self.lot_id.name)]}


class KaRecondLine(models.Model):
    _name = 'ka.recond.line'
    _description = 'Ancien / nouveau résultat'

    recond_id = fields.Many2one('ka.recond', required=True, ondelete='cascade')
    test = fields.Selection(TESTS, string='Test', required=True)
    ancien = fields.Float(string='Anciens résultats (historisés)', digits=(8, 2), readonly=True)
    nouveau = fields.Float(string='Nouveaux résultats', digits=(8, 2))


class KaSpecHisto(models.Model):
    _name = 'ka.spec.histo'
    _description = 'Historique des spécifications'
    _order = 'id desc'

    lot_name = fields.Char(string='Lot (colis)')
    recond_id = fields.Many2one('ka.recond', string='Ordre')
    date = fields.Datetime(default=fields.Datetime.now)
    valeurs = fields.Char(string='Résultats historisés')
