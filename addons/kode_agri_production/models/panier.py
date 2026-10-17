from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import POIDS_BALLE, TRACABILITE


class KaPanier(models.Model):
    _name = 'ka.panier'
    _description = 'Déclaration de panier'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'chrono desc'

    name = fields.Char(string='N° panier', required=True)
    chrono = fields.Char(string='N° chronologique', readonly=True, copy=False, default='Nouveau')
    of_id = fields.Many2one('ka.of', string='OF', required=True, ondelete='cascade')
    date_production = fields.Date(string='Date de production', default=fields.Date.context_today)
    sechoir_id = fields.Many2one('mrp.workcenter', string='Séchoir')
    cycle_min = fields.Integer(string='Cycle de séchage (min)')
    nb_pains = fields.Integer(string='Nombre de pains')
    nb_balles = fields.Integer(string='Nombre de balles')
    poids_balles = fields.Float(string='Poids des balles (kg)', compute='_compute_poids', store=True, digits=(8, 0))
    temp_bruleur1 = fields.Float(string='Température brûleur 1', digits=(5, 0))
    temp_bruleur2 = fields.Float(string='Température brûleur 2', digits=(5, 0))
    temp_balles = fields.Float(string='Température des balles', digits=(5, 0))
    heure_sortie = fields.Datetime(string='Heure de sortie du séchoir')
    tracabilite = fields.Selection(related='of_id.tracabilite', string='Statut de traçabilité', store=True)
    user_id = fields.Many2one('res.users', string='Utilisateur', default=lambda s: s.env.user, readonly=True)
    state = fields.Selection([('ouvert', 'Ouvert'), ('controle', 'Contrôle qualité'), ('valide', 'Validé'),
                              ('cloture', 'Clôturé'), ('annule', 'Annulé')], default='ouvert', string='Statut',
                             tracking=True)
    colis_line_ids = fields.One2many('ka.colis.panier', 'panier_id', string='Colis rattachés')
    balles_restantes = fields.Integer(compute='_compute_restantes', string='Balles restantes', store=True)
    qc_ids = fields.One2many('ka.qc.panier', 'panier_id', string='Contrôles qualité')
    qc_label = fields.Char(compute='_compute_qc_label', string='Contrôle qualité')
    notes = fields.Text(string='Notes')

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — panier %s · OF %s' % (self.chrono, self.name, self.of_id.name or '')

    @api.depends('nb_balles')
    def _compute_poids(self):
        for p in self:
            p.poids_balles = p.nb_balles * POIDS_BALLE

    @api.depends('nb_balles', 'colis_line_ids.balles', 'colis_line_ids.colis_id.state')
    def _compute_restantes(self):
        for p in self:
            used = sum(p.colis_line_ids.filtered(lambda l: l.colis_id.state != 'annule').mapped('balles'))
            p.balles_restantes = p.nb_balles - used

    @api.depends('qc_ids.state', 'qc_ids.p0', 'qc_ids.pri')
    def _compute_qc_label(self):
        for p in self:
            qc = p.qc_ids.filtered(lambda q: q.state == 'valide')[:1]
            p.qc_label = 'Validé %d/%d' % (qc.p0, qc.pri) if qc else 'Aucun contrôle'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('chrono', 'Nouveau') == 'Nouveau':
                vals['chrono'] = self.env['ir.sequence'].next_by_code('ka.panier')
        return super().create(vals_list)

    def action_passer_controle(self):
        for p in self:
            if p.state != 'ouvert':
                raise UserError(_('Seul un panier ouvert peut être envoyé en contrôle qualité.'))
            self.env['ka.qc.panier'].create({'panier_id': p.id})
            p.state = 'controle'

    def action_annuler_controle(self):
        for p in self.filtered(lambda p: p.state == 'controle'):
            p.qc_ids.filtered(lambda q: q.state == 'brouillon').unlink()
            p.state = 'ouvert'

    def action_valider(self):
        for p in self:
            if not p.nb_balles:
                raise UserError(_('Renseignez le nombre de balles du panier.'))
            p.state = 'valide'

    def action_annuler(self):
        for p in self:
            if p.colis_line_ids.filtered(lambda l: l.colis_id.state == 'valide'):
                raise UserError(_('Des colis validés consomment ce panier : annulation impossible.'))
            p.state = 'ouvert'
