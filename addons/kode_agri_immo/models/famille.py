from odoo import _, api, fields, models

METHODES = [('lineaire', 'Linéaire'), ('degressif', 'Dégressif')]


class KaImmoFamille(models.Model):
    """Famille d'immobilisations : règles d'amortissement et comptes par défaut (écran 3.1c)."""
    _name = 'ka.immo.famille'
    _description = "Famille d'immobilisations"
    _inherit = ['ka.document']
    _order = 'code'

    code = fields.Char(string='Famille', required=True)
    name = fields.Char(string='Intitulé', required=True)
    methode = fields.Selection(METHODES, string="Mode d'amortissement", required=True, default='lineaire')
    duree = fields.Integer(string='Durée', required=True, default=10, help='En années')
    cpt_immo = fields.Char(string="Compte d'immobilisation", required=True, help='Ex. 2154 — Matériel industriel')
    cpt_amort = fields.Char(string="Compte d'amortissement", required=True)
    cpt_dotation = fields.Char(string='Compte de dotation', required=True)
    axe = fields.Char(string='Axe analytique', default='LIGNE — Ligne de production')
    creation_facture = fields.Boolean(string='Création depuis facture', default=True)
    immo_ids = fields.One2many('ka.immo', 'famille_id', string='Immobilisations rattachées')
    nb_immos = fields.Integer(compute='_compute_nb', string='Immobilisations rattachées')
    cpt_immo_txt = fields.Char(compute='_compute_comptes_txt', string='Immobilisation')
    cpt_amort_txt = fields.Char(compute='_compute_comptes_txt', string='Amortissement cumulé')
    cpt_dotation_txt = fields.Char(compute='_compute_comptes_txt', string='Dotation')

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — %s' % (self.code or '', self.name or '')

    @api.depends('immo_ids')
    def _compute_nb(self):
        for f in self:
            f.nb_immos = len(f.immo_ids)

    @api.depends('cpt_immo', 'cpt_amort', 'cpt_dotation')
    def _compute_comptes_txt(self):
        from .immo import libelle_compte
        for f in self:
            f.cpt_immo_txt = libelle_compte(self.env, f.cpt_immo)
            f.cpt_amort_txt = libelle_compte(self.env, f.cpt_amort)
            f.cpt_dotation_txt = libelle_compte(self.env, f.cpt_dotation)

    @api.depends('name')
    def _compute_display_name(self):
        for f in self:   # maquettes 3.1 et 3.1c : la catégorie est désignée par son intitulé
            f.display_name = f.name or f.code or ''

    def action_immos(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Immobilisations rattachées', 'res_model': 'ka.immo',
                'view_mode': 'list,form', 'domain': [('famille_id', '=', self.id)]}
