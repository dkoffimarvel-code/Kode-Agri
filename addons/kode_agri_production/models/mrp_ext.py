from odoo import api, fields, models


class MrpRoutingWorkcenter(models.Model):
    """Gamme : temps opératoire (h) et cadence (/h) calculés à partir de la durée de l'opération (§ 4.1)."""
    _inherit = 'mrp.routing.workcenter'

    ka_temps_h = fields.Float(string='Temps opératoire (h)', compute='_compute_ka_cadence', digits=(6, 3))
    ka_cadence = fields.Float(string='Cadence (/h)', compute='_compute_ka_cadence', digits=(8, 1))
    ka_centre = fields.Selection(related='workcenter_id.ka_centre', string='Centre de charge')
    ka_code_poste = fields.Char(related='workcenter_id.code', string='Poste de charge')
    ka_type_poste = fields.Selection(related='workcenter_id.ka_type_poste', string='Type')
    ka_num_op = fields.Char(string='N° opér.', compute='_compute_ka_num_op')

    @api.depends('sequence')
    def _compute_ka_num_op(self):
        for op in self:
            op.ka_num_op = '%03d' % (op.sequence or 0)

    @api.depends('time_cycle_manual')
    def _compute_ka_cadence(self):
        for op in self:
            op.ka_temps_h = (op.time_cycle_manual or 0.0) / 60.0
            op.ka_cadence = (1.0 / op.ka_temps_h) if op.ka_temps_h else 0.0


class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    ka_centre = fields.Selection([('CC01', 'CC01 — Prélavage'), ('CC02', 'CC02 — Zone humide'),
                                  ('CC03', 'CC03 — Zone sèche'), ('CC04', 'CC04 — Mise en moule')],
                                 string='Centre de charge')
    ka_type_poste = fields.Selection([('poste', 'Poste de charge'), ('centre', 'Centre de charge (MO)')],
                                     string='Type', default='poste')


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    ka_gamme = fields.Char(string='Gamme', default='GAM-TSR-01')

    @api.model
    def ka_init_nomenclature(self):
        """Nomenclature TSR (1 kg de TSR consomme 1 kg de fond de tasse actif) et gamme GAM-TSR-01 (§ 4.1).
        Créée en Python : les expressions eval d'un fichier de données XML n'ont pas accès à l'environnement."""
        tsr = self.env.ref('kode_agri_production.product_tsr')
        if self.search([('product_tmpl_id', '=', tsr.product_tmpl_id.id)], limit=1):
            return
        fdt = self.env.ref('kode_agri_planteur.product_fdt_hevea')
        bom = self.create({'product_tmpl_id': tsr.product_tmpl_id.id, 'code': '1 — Production', 'product_qty': 1.0,
                           'bom_line_ids': [(0, 0, {'product_id': fdt.id, 'product_qty': 1.0})]})
        # (n° d'opération, poste de charge, intitulé, temps opératoire en heures par unité de base)
        gamme = [('010', 'pc01_02', 'Slab cutter 1', .020), ('020', 'pc02_04', 'Pre-breaker', .015), ('030', 'pc02_06', 'Shredder à granuler', .025),
                 ('040', 'pc02_10', 'Crêpeuse 8', .022), ('050', 'pc02_11', 'Shredder final (4)', .030), ('090', 'pc03_01', 'Séchoir 1', .050),
                 ('110', 'pc03_03', 'Pressage et habillage', .018), ('120', 'pc03_05', 'Conditionnement', .015)]
        for n, poste, nom, heures in gamme:
            self.env['mrp.routing.workcenter'].create({
                'bom_id': bom.id, 'name': nom, 'sequence': int(n), 'time_cycle_manual': round(heures * 60, 3),
                'workcenter_id': self.env.ref('kode_agri_production.wc_%s' % poste).id})
    ka_etat = fields.Selection([('brouillon', 'Brouillon'), ('validee', 'Validée')], string='Statut',
                               default='validee')
    ka_subtitle = fields.Char(compute='_compute_ka_subtitle')

    @api.depends('product_tmpl_id', 'type')
    def _compute_ka_subtitle(self):
        types = {'normal': 'Fabriqué', 'phantom': 'Kit'}
        for b in self:
            article = b.product_tmpl_id
            nature = 'Article non spécifié' if (article.default_code or '') == 'TSR' else (article.name or '')
            b.ka_subtitle = '%s · Nomenclature de type %s' % (nature, types.get(b.type, b.type or ''))

    def action_copier(self):
        self.ensure_one()
        new = self.copy()
        return {'type': 'ir.actions.act_window', 'res_model': 'mrp.bom', 'res_id': new.id, 'view_mode': 'form'}

    def action_cout_standard(self):
        """Coût standard opératoire = Σ temps (h) × coût horaire du poste (§ 4.1)."""
        self.ensure_one()
        cout = sum(op.ka_temps_h * op.workcenter_id.costs_hour for op in self.operation_ids)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'Coût standard', 'type': 'success', 'sticky': False,
                           'message': 'Coût opératoire standard : %.0f par unité de base.' % cout}}
