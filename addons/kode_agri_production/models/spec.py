from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import TESTS, TESTS_PCT, TEXTURES, TRACABILITE


class KaSpec(models.Model):
    """Saisie des résultats d'analyse laboratoire d'un colis (7 tests) et classement par grade (§ 4.2.5)."""
    _name = 'ka.spec'
    _description = "Spécification laboratoire d'un colis"
    _inherit = ['ka.document', 'mail.thread']
    _order = 'id desc'

    lot_id = fields.Many2one('stock.lot', string='Lot (colis)', required=True, domain=[('ka_est_colis', '=', True)])
    line_ids = fields.One2many('ka.spec.line', 'spec_id', string='Résultats laboratoire')
    texture = fields.Selection(TEXTURES, string='Texture', default='conforme')
    grade_id = fields.Many2one('ka.grade', string='Grade déterminé', compute='_compute_grade', store=True)
    grade_label = fields.Char(compute='_compute_grade', store=True)
    product_id = fields.Many2one('product.product', string='Article créé', compute='_compute_grade', store=True)
    tracabilite = fields.Selection(related='lot_id.ka_tracabilite', string='Statut de traçabilité')
    state = fields.Selection([('a_specifier', 'À spécifier'), ('specifie', 'Validée')], default='a_specifier',
                             string='Statut', tracking=True)
    # résultats présentés champ par champ (écran 4.5) : lus et écrits dans les lignes de résultats
    r_p0 = fields.Float(string='P0', compute='_compute_r', inverse='_inverse_r', digits=(8, 0))
    r_pri = fields.Float(string='PRI', compute='_compute_r', inverse='_inverse_r', digits=(8, 0))
    r_ml = fields.Float(string='Viscosité Mooney (ML)', compute='_compute_r', inverse='_inverse_r', digits=(8, 0))
    r_imp = fields.Float(string='Impuretés', compute='_compute_r', inverse='_inverse_r', digits=(8, 2))
    r_azote = fields.Float(string='Azote', compute='_compute_r', inverse='_inverse_r', digits=(8, 2))
    r_cendres = fields.Float(string='Cendres', compute='_compute_r', inverse='_inverse_r', digits=(8, 2))
    r_vm = fields.Float(string='Matière volatile', compute='_compute_r', inverse='_inverse_r', digits=(8, 2))
    statut_colis = fields.Char(compute='_compute_grade_txt', string='Statut colis')
    ka_valid_txt = fields.Char(compute='_compute_grade_txt', string='Résultat de la validation')

    @api.depends('lot_id.name')
    def _compute_display_name(self):
        for spec in self:
            spec.display_name = 'SPEC %s' % (spec.lot_id.name or '')

    def _ka_subtitle(self):
        self.ensure_one()
        return "À la validation : création de l'article définitif (entrée stock) et sortie du %s à même quantité" % (
            self.lot_id.product_id.default_code or 'TSR')

    @api.depends('line_ids.resultat', 'line_ids.test')
    def _compute_r(self):
        for spec in self:
            res = spec.ka_resultats()
            for t, _label in TESTS:
                spec['r_%s' % t] = res.get(t, 0.0)

    def _inverse_r(self):
        for spec in self:
            existants = {l.test: l for l in spec.line_ids}
            cmds = []
            for t, _label in TESTS:
                valeur = spec['r_%s' % t]
                if t in existants:
                    if existants[t].resultat != valeur:
                        cmds.append(Command.update(existants[t].id, {'resultat': valeur}))
                else:
                    cmds.append(Command.create({'test': t, 'resultat': valeur}))
            if cmds:
                spec.line_ids = cmds

    @api.depends('grade_id', 'product_id', 'lot_id', 'state')
    def _compute_grade_txt(self):
        for spec in self:
            spec.statut_colis = spec.grade_label or ''
            if spec.product_id:
                spec.ka_valid_txt = ("Résultat : entrée en stock de l'article %s (série %s), sortie du %s en "
                                     "contrepartie. Traçabilité conservée.") % (
                    spec.product_id.default_code or spec.product_id.name, spec.lot_id.name or '',
                    'TSR non spécifié' if (spec.lot_id.product_id.default_code or 'TSR') == 'TSR'
                    else spec.lot_id.product_id.display_name)
            else:
                spec.ka_valid_txt = ("Résultat : à la validation, l'article définitif entre en stock sous le même "
                                     "numéro de série et le TSR non spécifié sort en contrepartie.")

    def action_saisir_mesures(self):
        """Ouvre la grille détaillée des 7 résultats (unité, seuil, conformité)."""
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Mesures laboratoire', 'res_model': 'ka.spec.line',
                'view_mode': 'list', 'domain': [('spec_id', '=', self.id)], 'context': {'default_spec_id': self.id}}

    @api.model
    def _default_lines(self):
        return [Command.create({'test': t}) for t, _label in TESTS]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('line_ids'):
                vals['line_ids'] = self._default_lines()
        return super().create(vals_list)

    def ka_resultats(self):
        self.ensure_one()
        return {l.test: l.resultat for l in self.line_ids}

    @api.depends('line_ids.resultat')
    def _compute_grade(self):
        grades = self.env['ka.grade'].search([], order='sequence, id')
        for spec in self:
            resultats = spec.ka_resultats() if spec.line_ids else {}
            filled = any(resultats.values())
            grade = False
            if filled:
                for g in grades.filtered(lambda g: not g.hors_specs):
                    if g.verifie(resultats):
                        grade = g
                        break
                grade = grade or grades.filtered('hors_specs')[:1]
            spec.grade_id = grade
            spec.product_id = grade.product_id if grade else False
            spec.grade_label = ('%s — %s' % (grade.code, 'Standard' if not grade.hors_specs else 'Hors spécifications')
                                if grade else '')

    def action_valider(self):
        """Valide la spécification : l'article définitif entre en stock, le TSR en sort (même lot)."""
        for spec in self:
            if spec.state != 'a_specifier':
                continue
            if not spec.grade_id:
                raise UserError(_('Saisissez les résultats du laboratoire avant de valider.'))
            lot = spec.lot_id
            new_lot, of = lot.ka_reclasser(spec.grade_id.product_id, _('Spécification %s') % spec.grade_id.code)
            texture = spec.texture
            vals = {'ka_spec_id': spec.id}
            if texture != 'conforme':
                statut = self.env['ka.statut.colis'].search([('defaut', '=', True), (
                    'name', 'ilike', dict(TEXTURES)[texture])], limit=1)
                vals.update(ka_etat='Q', ka_statut_id=statut.id, ka_motif=dict(TEXTURES)[texture])
            else:
                vals.update(ka_etat='Q', ka_statut_id=self.env['ka.statut.colis'].search([
                    ('article_code', '=', spec.grade_id.code), ('defaut', '=', False)], limit=1).id)
            new_lot.write(vals)
            if new_lot != lot:
                spec.lot_id = new_lot
            spec.state = 'specifie'

    def action_certificat(self):
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _("Certificat d'analyse"), 'type': 'success', 'sticky': False,
                           'message': _("Certificat du lot %s généré à partir des mesures.") % self.lot_id.name}}


class KaSpecLine(models.Model):
    _name = 'ka.spec.line'
    _description = "Résultat d'analyse"
    _order = 'id'

    spec_id = fields.Many2one('ka.spec', required=True, ondelete='cascade')
    test = fields.Selection(TESTS, required=True, string='Test')
    resultat = fields.Float(string='Résultat', digits=(8, 2))
    unite = fields.Char(compute='_compute_ref', string='Unité')
    seuil = fields.Char(compute='_compute_ref', string='Seuil TSR10')
    conformite = fields.Selection([('conforme', 'Conforme'), ('non_conforme', 'Non conforme'),
                                   ('a_saisir', 'À saisir')], compute='_compute_ref', string='Conformité')

    @api.depends('test', 'resultat')
    def _compute_ref(self):
        tsr10 = self.env['ka.grade'].search([('code', '=', 'TSR10')], limit=1)
        for l in self:
            seuil = tsr10.seuil_ids.filtered(lambda s: s.test == l.test)[:1]
            l.unite = '%' if l.test in TESTS_PCT else ''
            l.seuil = seuil.texte or ''
            if seuil.operateur == 'client' or (seuil and l.resultat and seuil.conforme(l.resultat)):
                l.conformite = 'conforme'
            elif l.resultat:
                l.conformite = 'non_conforme'
            else:
                l.conformite = 'a_saisir'
