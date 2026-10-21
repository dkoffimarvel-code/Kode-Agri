from odoo import _, api, fields, models
from odoo.exceptions import UserError



class KaMntDemande(models.Model):
    """Demande d'intervention corrective (§ 10.5) : point d'entrée du correctif, émise par la production ou la
    maintenance (y compris depuis le mobile), qualifiée, priorisée puis convertie en OT ou traitée en urgence."""
    _name = 'ka.mnt.demande'
    _description = "Demande d'intervention"
    _inherit = ['ka.document', 'mail.thread', 'mail.activity.mixin']
    _order = 'date desc, name desc'

    name = fields.Char(string='N° demande', readonly=True, copy=False, default='Nouveau')
    titre = fields.Char(string='Objet', required=True, help='Ex. Allumage instable — brûleur biomasse')
    equipement_id = fields.Many2one('ka.mnt.equipement', string='Équipement', required=True)
    workcenter_id = fields.Many2one(related='equipement_id.workcenter_id', string='Poste de charge')
    sous_ensemble_id = fields.Many2one('ka.mnt.equipement', string='Sous-ensemble',
                                       domain="[('parent_id', '=', equipement_id)]")
    criticite = fields.Selection(related='equipement_id.criticite', string='Criticité')
    criticite_txt = fields.Char(related='equipement_id.criticite_txt', string='Criticité équipement')
    etat_equipement = fields.Selection([('marche', 'En marche'), ('degrade', 'Marche dégradée'), ('arret_total', "À l'arrêt total")],
                                       string='État équipement', default='degrade', required=True)
    type = fields.Selection([('correctif', 'Corrective'), ('ameliorative', 'Améliorative')], string='Type de maintenance',
                            default='correctif', required=True)
    equipe_id = fields.Many2one('ka.mnt.equipe', string='Équipe de maintenance')
    technicien_id = fields.Many2one('ka.rh.employe', string='Technicien')
    priorite = fields.Selection([('0', 'Basse'), ('1', 'Normale'), ('2', 'Haute'), ('3', 'Critique')], string='Priorité',
                                default='1')
    nature_panne = fields.Char(string='Nature de la panne')
    description = fields.Text(string='Description détaillée')
    demandeur_id = fields.Many2one('res.users', string='Créée par', default=lambda s: s.env.user, readonly=True)
    date = fields.Datetime(string='Date', default=fields.Datetime.now, readonly=True)
    canal = fields.Selection([('telephone', 'Téléphone'), ('mobile', 'Application mobile'), ('terrain', 'Terrain'),
                              ('courriel', 'Courriel')], string='Canal', default='telephone')
    qualification = fields.Text(string='Qualification', help='Diagnostic du responsable maintenance')
    urgence = fields.Boolean(string='Traitée en urgence', readonly=True)
    ot_id = fields.Many2one('ka.mnt.ot', string='Référence OT', readonly=True, copy=False)
    nb_interventions = fields.Integer(compute='_compute_interventions', string='Interventions passées')
    nb_pj = fields.Integer(compute='_compute_interventions', string='Pièces jointes')
    state = fields.Selection([('nouvelle', 'Nouvelle demande'), ('qualification', 'En qualification'),
                              ('ot', 'Ordre de travail'), ('cloture', 'Clôturé')], default='nouvelle', string='Statut',
                             tracking=True)

    @api.depends('titre')
    def _compute_display_name(self):
        for d in self:
            d.display_name = d.titre or d.name

    def _ka_subtitle(self):
        self.ensure_one()
        quand = fields.Datetime.context_timestamp(self, self.date).strftime('%d/%m/%Y %H:%M') if self.date else ''
        return _('Demande %s · créée par %s · %s · Canal : %s') % (
            self.name, self.demandeur_id.name or '', quand, dict(self._fields['canal'].selection).get(self.canal, ''))

    @api.depends('equipement_id')
    def _compute_interventions(self):
        for d in self:
            d.nb_interventions = self.env['ka.mnt.ot'].search_count(
                [('equipement_id', 'child_of', d.equipement_id.id), ('state', '=', 'cloture')]) if d.equipement_id else 0
            d.nb_pj = self.env['ir.attachment'].search_count([('res_model', '=', self._name), ('res_id', '=', d.id)]) if d.id else 0

    @api.onchange('equipement_id')
    def _onchange_equipement(self):
        self.equipe_id = self.equipement_id.equipe_id
        if self.equipement_id.criticite == 'critique':
            self.priorite = '2'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.mnt.demande')
        return super().create(vals_list)

    def action_qualifier(self):
        self.filtered(lambda d: d.state == 'nouvelle').write({'state': 'qualification'})

    def _creer_ot(self, urgence=False):
        self.ensure_one()
        if self.ot_id:
            raise UserError(_('La demande est déjà convertie en %s.') % self.ot_id.name)
        prio = {'0': 'basse', '1': 'normale', '2': 'haute', '3': 'critique'}[self.priorite or '1']
        ot = self.env['ka.mnt.ot'].create({
            'equipement_id': self.equipement_id.id, 'sous_ensemble_id': self.sous_ensemble_id.id, 'type': 'correctif'
            if self.type == 'correctif' else 'ameliorative', 'priorite': 'critique' if urgence else prio,
            'objet': self.nature_panne or self.titre, 'technicien_id': self.technicien_id.id, 'demande_id': self.id,
            'cause': self.qualification})
        if self.equipe_id:
            ot.equipe_id = self.equipe_id
        self.write({'ot_id': ot.id, 'state': 'ot', 'urgence': urgence})
        if self.etat_equipement == 'arret_total':
            self.equipement_id.write({'state': 'arret'})
        return ot

    def action_convertir(self):
        self.ensure_one()
        ot = self._creer_ot()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.mnt.ot', 'res_id': ot.id, 'view_mode': 'form'}

    def action_urgence(self):
        """Équipement critique à l'arrêt : OT créé en priorité critique et démarré immédiatement."""
        self.ensure_one()
        ot = self._creer_ot(urgence=True)
        if ot.technicien_id:
            ot.action_demarrer()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.mnt.ot', 'res_id': ot.id, 'view_mode': 'form'}

    def action_open_ot(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.mnt.ot', 'res_id': self.ot_id.id, 'view_mode': 'form'}

    def action_open_historique(self):
        return self.equipement_id.action_open_ots()

    def action_open_equipement(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.mnt.equipement', 'res_id': self.equipement_id.id,
                'view_mode': 'form'}
