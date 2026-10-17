from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import ARMATEURS, DETENTION_JOURS, POIDS_COLIS, spec_ok


class KaConteneur(models.Model):
    """Équivalent conteneur : colis alloués au sous-contrat, plombage, empotage, port, embarquement."""
    _name = 'ka.conteneur'
    _description = 'Équivalent conteneur'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° équivalent conteneur', readonly=True, copy=False, default='Nouveau')
    serie = fields.Char(string='N° série conteneur', required=True)
    sous_contrat_id = fields.Many2one('ka.sous.contrat', string='Sous-contrat', required=True)
    voyage_id = fields.Many2one('ka.voyage', string='Ordre de voyage')
    armateur = fields.Selection(ARMATEURS, string='Armateur')
    plomb = fields.Char(string='N° de plomb')
    mode_chargement = fields.Char(compute='_compute_mode', string='Mode de chargement')
    capacite = fields.Integer(compute='_compute_mode')
    colis_ids = fields.One2many('ka.conteneur.colis', 'conteneur_id', string='Colis alloués')
    nb_colis = fields.Integer(compute='_compute_colis')
    colis_txt = fields.Char(compute='_compute_colis', string='Colis alloués')
    spec_txt = fields.Char(default='Héritées du sous-contrat', readonly=True, string='Spécifications')
    date_entree_parc = fields.Date(string="Entrée parc externe")
    tare = fields.Float(string='Tare', digits=(8, 0))
    date_prise = fields.Date(related='voyage_id.date_prise_effective', string='Prise du conteneur')
    date_entree_port = fields.Date(string='Entrée au port')
    statut_transitaire = fields.Char(string='Statut transitaire', default='Disponible au parc')
    transfert_effectue = fields.Boolean(string='Transfert armateur effectué')
    embarque = fields.Boolean(string='Embarqué')
    transfert_label = fields.Char(compute='_compute_labels', string='Transfert armateur')
    embarquement_label = fields.Char(compute='_compute_labels', string="Statut d'embarquement")
    lot_conteneur_id = fields.Many2one('stock.lot', string='Article conteneur (série)', readonly=True, copy=False)
    state = fields.Selection([('affecte', 'Affecté'), ('plombe', 'Plombé'), ('empote', 'Empoté'),
                              ('au_port', 'Au port'), ('embarque', 'Embarqué')], default='affecte', string='Statut',
                             tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — sous-contrat %s · %s' % (self.name, self.sous_contrat_id.name or '', self.serie or '')

    @api.depends('sous_contrat_id.conditionnement')
    def _compute_mode(self):
        for c in self:
            sc = c.sous_contrat_id
            n = sc.colis_par_conteneur() if sc else 16
            c.capacite = n
            c.mode_chargement = '%s (%s colis)' % ('Vrac' if sc.conditionnement == 'vrac' else 'Palette', n)

    @api.depends('transfert_effectue', 'embarque', 'state')
    def _compute_labels(self):
        for c in self:
            c.transfert_label = 'Effectué' if c.transfert_effectue else 'À faire'
            c.embarquement_label = 'Embarqué' if (c.embarque or c.state == 'embarque') else 'À quai'

    @api.depends('colis_ids', 'capacite')
    def _compute_colis(self):
        for c in self:
            c.nb_colis = len(c.colis_ids)
            c.colis_txt = '%s / %s' % (c.nb_colis, c.capacite)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.conteneur')
            if not vals.get('armateur') and vals.get('sous_contrat_id'):
                vals['armateur'] = self.env['ka.sous.contrat'].browse(vals['sous_contrat_id']).armateur
        return super().create(vals_list)

    def poids_colis(self):
        self.ensure_one()
        return sum(self.colis_ids.lot_id.mapped('product_qty')) or len(self.colis_ids) * POIDS_COLIS

    def jours_hors_franchise(self):
        self.ensure_one()
        if not (self.date_entree_port and self.date_prise):
            return 0
        franchise = DETENTION_JOURS.get(self.armateur or '', 30)
        return max(0, (self.date_entree_port - self.date_prise).days - franchise)

    # ---- allocation des colis (RG-5.1, RG-5.11, RG-5.12, RG-5.15) ----------------------------------------------
    def _lots_eligibles(self):
        """Seuls les colis libérés (statut A), conformes aux spécifications du contrat, sans défaut de texture,
        du bon grade, et pas déjà alloués sont proposés."""
        self.ensure_one()
        sc = self.sous_contrat_id
        specs = sc.contrat_id.spec_ids
        deja = self.env['ka.conteneur.colis'].search([]).lot_id
        lots = self.env['stock.lot'].search([
            ('ka_est_colis', '=', True), ('ka_etat', '=', 'A'), ('product_id', '=', sc.product_id.id),
            ('ka_tracabilite', '=', sc.tracabilite), ('id', 'not in', deja.ids)])
        ok = self.env['stock.lot']
        for lot in lots:
            if lot.ka_motif or lot.ka_statut_id.defaut:      # RG-5.15 : points blancs / défaut de texture exclus
                continue
            if lot.product_qty <= 0:
                continue
            if lot.ka_spec_id and self._conforme(lot, specs):
                ok |= lot
        return ok

    @api.model
    def _conforme(self, lot, specs):
        res = lot.ka_spec_id.ka_resultats() if lot.ka_spec_id else {}
        return all(spec_ok(s.applique, s.standard, res.get(s.test)) for s in specs)

    def action_allouer(self):
        for c in self:
            libres = c.capacite - c.nb_colis
            if libres <= 0:
                raise UserError(_('Le conteneur est complet (%s colis).') % c.capacite)
            lots = c._lots_eligibles()[:libres]
            if not lots:
                raise UserError(_('Aucun colis libéré conforme aux spécifications du contrat n\'est disponible.'))
            c.colis_ids = [Command.create({'lot_id': l.id,
                                           'palette': self.env['ir.sequence'].next_by_code('ka.palette')}) for l in lots]

    def write(self, vals):
        res = super().write(vals)
        if vals.get('plomb'):
            self.filtered(lambda c: c.state == 'affecte').write({'state': 'plombe'})
        return res

    def action_empoter(self):
        for c in self:
            if not c.colis_ids:
                raise UserError(_('Allouez des colis avant d\'empoter.'))
            if not c.plomb:
                raise UserError(_('Le N° de plomb est obligatoire.'))
            c.state = 'empote'
            v = c.voyage_id
            if v:   # RG-5.17 : voyage à clôturer quand tous ses conteneurs sont en cours d'empotage
                v.state = 'a_cloturer' if all(x.state in ('empote', 'au_port', 'embarque') for x in v.conteneur_ids) else 'empotage'

    def action_documents(self):
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Documents'), 'type': 'success', 'sticky': False,
                           'message': _("Bordereau d'expédition, certificat d'analyse par palette et certificat de "
                                        "traitement thermique du conteneur %s.") % self.serie}}

    def _transferer_colis(self, dest):
        for lot in self.colis_ids.lot_id:
            src = lot.ka_location()
            if src and src != dest:
                self.env['stock.lot'].ka_move(lot.product_id, lot, lot.product_qty, src, dest)


class KaConteneurColis(models.Model):
    _name = 'ka.conteneur.colis'
    _description = 'Colis alloué à un équivalent conteneur'
    _order = 'id'

    conteneur_id = fields.Many2one('ka.conteneur', required=True, ondelete='cascade')
    palette = fields.Char(string='Palette')
    lot_id = fields.Many2one('stock.lot', string='Lot (colis)', required=True, domain=[('ka_est_colis', '=', True)])
    product_id = fields.Many2one(related='lot_id.product_id', string='Article')
    statut = fields.Char(compute='_compute_vals', string='Statut')
    p0_pri = fields.Char(compute='_compute_vals', string='P0 / PRI')
    conformite = fields.Selection([('conforme', 'Conforme'), ('non_conforme', 'Non conforme')],
                                  compute='_compute_vals', string='Conformité')

    @api.depends('lot_id', 'conteneur_id.sous_contrat_id')
    def _compute_vals(self):
        for l in self:
            res = l.lot_id.ka_spec_id.ka_resultats() if l.lot_id.ka_spec_id else {}
            l.statut = l.lot_id.ka_etat or ''
            l.p0_pri = '%d / %d' % (res.get('p0', 0), res.get('pri', 0))
            specs = l.conteneur_id.sous_contrat_id.contrat_id.spec_ids
            l.conformite = 'conforme' if l.conteneur_id._conforme(l.lot_id, specs) else 'non_conforme'

    @api.constrains('lot_id')
    def _check_lot_unique(self):
        for l in self:
            if self.search_count([('lot_id', '=', l.lot_id.id), ('id', '!=', l.id)]):
                raise UserError(_('Ce colis est déjà alloué à un équivalent conteneur.'))
            if l.lot_id.ka_motif or l.lot_id.ka_statut_id.defaut:
                raise UserError(_('Un colis à défaut de texture (points blancs...) ne peut pas être alloué (RG-5.15).'))
