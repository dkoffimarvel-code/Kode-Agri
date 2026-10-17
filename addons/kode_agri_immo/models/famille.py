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

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — %s' % (self.code or '', self.name or '')

    @api.depends('immo_ids')
    def _compute_nb(self):
        for f in self:
            f.nb_immos = len(f.immo_ids)

    def _compute_display_name(self):
        for f in self:
            f.display_name = '%s — %s' % (f.code, f.name)

    def action_immos(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Immobilisations rattachées', 'res_model': 'ka.immo',
                'view_mode': 'list,form', 'domain': [('famille_id', '=', self.id)]}
