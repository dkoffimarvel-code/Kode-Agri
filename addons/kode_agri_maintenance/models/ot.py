from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.kode_agri_gestion.models.common import plan_col, plan_de, section

from .equipement import nb

TYPES = [('preventif', 'Préventif'), ('correctif', 'Correctif'), ('ameliorative', 'Amélioratif'),
         ('reglementaire', 'Réglementaire')]
PRIORITES = [('basse', 'Basse'), ('normale', 'Normale'), ('haute', 'Haute'), ('critique', 'Critique')]


def heures_txt(h):
    m = int(round((h or 0.0) * 60))
    return '%d h %02d' % (m // 60, m % 60) if m % 60 else '%d h' % (m // 60)


class KaMntOt(models.Model):
    """Ordre de travail (§ 10.4) : pièce centrale de la maintenance, préventif (issu d'un plan) ou correctif (issu d'une
    demande d'intervention). Il porte la main-d'œuvre, les pièces sorties du magasin (module 2), la sous-traitance, la
    cause et le remède, la durée d'arrêt ; sa clôture remet l'équipement en service, met à jour l'historique et les
    compteurs et impute le coût à l'équipement et au coût d'usinage (module 9)."""
    _name = 'ka.mnt.ot'
    _description = 'Ordre de travail de maintenance'
    _inherit = ['ka.document', 'mail.thread', 'mail.activity.mixin']
    _order = 'date_demande desc, name desc'

    name = fields.Char(string='N° OT', readonly=True, copy=False, default='Nouveau')
    objet = fields.Char(string='Objet', required=True, help='Ex. brûleur 1 défaillant')
    equipement_id = fields.Many2one('ka.mnt.equipement', string='Équipement', required=True,
                                    domain=[('niveau', 'in', ('machine', 'sous_ensemble'))])
    machine_id = fields.Many2one('ka.mnt.equipement', compute='_compute_machine', store=True, string='Machine')
    sous_ensemble_id = fields.Many2one('ka.mnt.equipement', string='Sous-ensemble',
                                       domain="[('parent_id', '=', equipement_id)]")
    type = fields.Selection(TYPES, string='Type', required=True, default='correctif', tracking=True)
    priorite = fields.Selection(PRIORITES, string='Priorité', required=True, default='normale', tracking=True)
    plan_id = fields.Many2one('ka.mnt.plan', string='Plan préventif', readonly=True)
    demande_id = fields.Many2one('ka.mnt.demande', string="Demande d'intervention", readonly=True)
    technicien_id = fields.Many2one('ka.rh.employe', string='Technicien')
    equipe_id = fields.Many2one('ka.mnt.equipe', string='Équipe', compute='_compute_equipe', store=True, readonly=False)
    date_demande = fields.Date(string='Date demande', required=True, default=fields.Date.context_today)
    fenetre_debut = fields.Datetime(string="Fenêtre d'arrêt — début")
    fenetre_fin = fields.Datetime(string="Fenêtre d'arrêt — fin")
    fenetre_txt = fields.Char(compute='_compute_txt', string="Fenêtre d'arrêt")
    duree_estimee = fields.Float(string='Durée estimée (h)', digits=(6, 1))
    duree_arret = fields.Float(string="Durée d'arrêt (h)", digits=(6, 2))
    duree_arret_txt = fields.Char(compute='_compute_txt', string="Durée d'arrêt")
    date_debut = fields.Datetime(string='Début réel', readonly=True, copy=False)
    date_cloture = fields.Date(string='Date de clôture', readonly=True, copy=False)
    compteur_cloture = fields.Float(string='Compteur à la clôture', digits=(12, 0))
    cause = fields.Text(string='Cause')
    remede = fields.Text(string='Remède')
    observations = fields.Text(string='Observations')
    ligne_ids = fields.One2many('ka.mnt.ot.ligne', 'ot_id', string="Main-d'œuvre et pièces consommées")
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    cout_mo = fields.Monetary(compute='_compute_couts', string="Main-d'œuvre", store=True)
    cout_pieces = fields.Monetary(compute='_compute_couts', string='Pièces', store=True)
    cout_st = fields.Monetary(compute='_compute_couts', string='Sous-traitance', store=True)
    cout_total = fields.Monetary(compute='_compute_couts', string="Coût de l'OT", store=True)
    cout_txt = fields.Char(compute='_compute_couts', string="Coût de l'OT")
    # sous-traitance (§ 10.6, RG-10.3)
    externe = fields.Boolean(string='Intervention externe', tracking=True)
    prestataire_id = fields.Many2one('res.partner', string='Prestataire', compute='_compute_prestataire', store=True,
                                     readonly=False)
    contrat_id = fields.Many2one('ka.mnt.contrat', string='Contrat de maintenance')
    da_id = fields.Many2one('ka.da', string="Demande d'achat", readonly=True, copy=False)
    ao_id = fields.Many2one('ka.ao', string="Appel d'offre", compute='_compute_achat')
    commande_id = fields.Many2one('ka.commande', string='Commande', copy=False)
    commande_state = fields.Selection(related='commande_id.state', string='Statut de la commande')
    facture_txt = fields.Char(compute='_compute_achat', string='Facturation')
    imputation_faite = fields.Boolean(readonly=True, copy=False)
    titre = fields.Char(compute='_compute_txt')
    info_txt = fields.Char(compute='_compute_txt')
    type_txt = fields.Char(compute='_compute_txt', string='Type')
    priorite_txt = fields.Char(compute='_compute_txt', string='Priorité')
    state = fields.Selection([('demande', 'Demande'), ('planifie', 'Planifié'), ('en_cours', 'En cours'),
                              ('attente_piece', 'En attente de pièce'), ('cloture', 'Clôturé'), ('annule', 'Annulé')],
                             default='demande', string='Statut', tracking=True)

    @api.depends('name', 'equipement_id')
    def _compute_display_name(self):
        for o in self:
            o.display_name = '%s — %s' % (o.name, (o.machine_id or o.equipement_id).name or '')

    def _ka_subtitle(self):
        self.ensure_one()
        return ' · '.join(x for x in ((self.machine_id or self.equipement_id).name, self.objet) if x)

    @api.depends('equipement_id', 'equipement_id.niveau', 'equipement_id.parent_id')
    def _compute_machine(self):
        for o in self:
            e = o.equipement_id
            o.machine_id = e.parent_id if e.niveau == 'sous_ensemble' and e.parent_id else e

    @api.depends('equipement_id')
    def _compute_equipe(self):
        for o in self:
            o.equipe_id = o.equipement_id.equipe_id or o.machine_id.equipe_id

    @api.depends('contrat_id')
    def _compute_prestataire(self):
        for o in self:
            if o.contrat_id:
                o.prestataire_id = o.contrat_id.prestataire_id

    @api.depends('fenetre_debut', 'fenetre_fin', 'duree_arret', 'type', 'priorite', 'equipement_id.criticite', 'name', 'externe')
    def _compute_txt(self):
        types, prio = dict(TYPES), dict(PRIORITES)
        for o in self:
            o.titre = _('Ordre de travail %s') % (o.name or '')
            o.type_txt, o.priorite_txt = types.get(o.type, ''), prio.get(o.priorite, '')
            if o.fenetre_debut:
                d = fields.Datetime.context_timestamp(o, o.fenetre_debut)
                f = fields.Datetime.context_timestamp(o, o.fenetre_fin) if o.fenetre_fin else False
                o.fenetre_txt = '%s %s–%s' % (d.strftime('%d/%m'), d.strftime('%H:%M'), f.strftime('%H:%M') if f else '')
            else:
                o.fenetre_txt = ''
            o.duree_arret_txt = heures_txt(o.duree_arret) if o.duree_arret else ''
            if o.externe:
                o.info_txt = _("OT externalisé : la clôture vaut réception de la prestation et autorise la facturation "
                               "(commande / OT-réception / facture, RG-10.3).")
            else:
                o.info_txt = _("OT %s%s. La consommation de pièces génère une sortie magasin (module 2) ; pièce "
                               "indisponible → demande d'achat.") % (
                    types.get(o.type, '').lower(),
                    _(' sur équipement critique') if o.equipement_id.criticite == 'critique' else '')

    @api.depends('ligne_ids.cout', 'ligne_ids.type')
    def _compute_couts(self):
        for o in self:
            o.cout_mo = sum(o.ligne_ids.filtered(lambda l: l.type == 'main_oeuvre').mapped('cout'))
            o.cout_pieces = sum(o.ligne_ids.filtered(lambda l: l.type == 'piece').mapped('cout'))
            o.cout_st = sum(o.ligne_ids.filtered(lambda l: l.type == 'sous_traitance').mapped('cout'))
            o.cout_total = o.cout_mo + o.cout_pieces + o.cout_st
            o.cout_txt = '%s FCFA' % nb(o.cout_total)

    @api.depends('da_id.ao_ids', 'commande_id.facture_ids.state')
    def _compute_achat(self):
        for o in self:
            o.ao_id = o.da_id.ao_ids[:1]
            factures = o.commande_id.facture_ids
            if not o.commande_id:
                o.facture_txt = ''
            elif not factures:
                o.facture_txt = _('En attente de la facture du prestataire') if o.state == 'cloture' else _('Service non encore fait')
            else:
                o.facture_txt = ', '.join('%s (%s)' % (f.name, dict(f._fields['state'].selection).get(f.state)) for f in factures)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.mnt.ot')
        return super().create(vals_list)

    # ---- cycle (§ 10.4) ---------------------------------------------------------------------------------------------
    def action_planifier(self):
        for o in self:
            if o.state not in ('demande', 'attente_piece'):
                raise UserError(_("L'OT est déjà planifié."))
            if not o.technicien_id and not o.externe:
                raise UserError(_('Affectez un technicien (ou externalisez l\'intervention) avant de planifier.'))
            o.state = 'planifie'

    def action_demarrer(self):
        for o in self:
            if o.state not in ('demande', 'planifie'):
                raise UserError(_("Seul un OT demandé ou planifié peut démarrer."))
            o.write({'state': 'en_cours', 'date_debut': fields.Datetime.now()})
            if o.type == 'correctif' or o.fenetre_debut:
                o.machine_id.state = 'arret'

    def action_demander_piece(self):
        """RG-10.2 : pièce indisponible → demande d'achat (workflow du module 2) ; l'OT attend la pièce."""
        for o in self:
            manquantes = [(l, l.quantite - l.product_id.qty_available) for l in o.ligne_ids
                          if l.type == 'piece' and l.product_id and l.product_id.qty_available < l.quantite]
            if not manquantes:
                raise UserError(_('Toutes les pièces sont disponibles en magasin.'))
            da = o._creer_da([(l.product_id, q, l.product_id.standard_price * q) for l, q in manquantes],
                             _('Pièces pour %s') % o.name, signee=False)
            o.write({'state': 'attente_piece'})
            o.message_post(body=_("Pièces indisponibles : demande d'achat %s créée (RG-10.2).") % da.name)
            return {'type': 'ir.actions.act_window', 'res_model': 'ka.da', 'res_id': da.id, 'view_mode': 'form'}

    def _site(self):
        return self.machine_id.site_id or self.env['ka.site'].search([], limit=1)

    def _creer_da(self, lignes, objet, signee, partenaire=None):
        if not self._site():
            raise UserError(_("Aucun site n'est paramétré (données de structure, module 2)."))
        da = self.env['ka.da'].create({
            'objet': objet, 'site_id': self._site().id, 'demandeur': self.env.user.name, 'partner_id': partenaire.id if partenaire else False,
            'date_besoin': fields.Date.context_today(self), 'priorite': 'urgente' if self.priorite == 'critique' else 'normale',
            'line_ids': [Command.create({'product_id': p.id, 'designation': p.name, 'qty': q, 'uom_id': p.uom_id.id, 'montant': m})
                         for p, q, m in lignes]})
        if signee:   # le diagnostic ou la qualification de l'OT vaut justification (RG-11.2 / § 10.6)
            da.write({'state': 'signee'})
        self.da_id = da
        return da

    def action_externaliser(self):
        """§ 10.6 : OT qualifié « intervention externe ».
        - prestataire sous contrat à l'intervention : demande d'achat pré-remplie (prestataire, tarif du contrat), signée,
          convertie en commande ;
        - sans contrat : demande d'achat convertie en appel d'offre pour mise en concurrence."""
        for o in self:
            if o.state in ('cloture', 'annule'):
                raise UserError(_("L'OT est clos."))
            if o.commande_id:
                raise UserError(_("L'OT est déjà rattaché à la commande %s.") % o.commande_id.name)
            o.externe = True
            c = o.contrat_id
            service = (c.product_id if c else False) or self.env.ref('kode_agri_maintenance.product_prestation_mnt').product_variant_id
            heures = o.duree_estimee or 1.0
            if c and c.type == 'forfait':
                o.message_post(body=_('Contrat forfaitaire %s : facturation périodique indépendante des OT, qui servent de '
                                      'justificatif de service fait (RG-10.3).') % c.name)
                continue
            if c:
                da = o._creer_da([(service, heures, c.tarif * heures)], _('Intervention %s — %s') % (o.name, c.name),
                                 signee=True, partenaire=c.prestataire_id)
                res = da.action_transformer()
                o.commande_id = res.get('res_id')
                o.commande_id.write({'state': 'a_signer'})
            else:
                da = o._creer_da([(service, heures, service.standard_price * heures)], _('Intervention %s') % o.name,
                                 signee=True, partenaire=o.prestataire_id or None)
                da.action_demande_prix()
            o.message_post(body=_("Intervention externalisée : demande d'achat %s%s.") % (
                da.name, (_(' → commande %s') % o.commande_id.name) if o.commande_id else _(" → appel d'offre")))

    def action_cloturer(self):
        """Clôture : sortie magasin des pièces (RG-10.2), réception automatique de la prestation externe (RG-10.3),
        remise en service, compteurs, plan préventif et imputation du coût au coût d'usinage (module 9)."""
        for o in self:
            if o.state not in ('en_cours', 'planifie'):
                raise UserError(_("Seul un OT démarré peut être clôturé."))
            if o.externe and o.ao_id and not o.commande_id:   # l'appel d'offre a abouti : la commande met à jour l'OT
                o.commande_id = o.ao_id.commande_id
            if o.externe and not (o.contrat_id and o.contrat_id.type == 'forfait'):
                if not o.commande_id or o.commande_id.state in ('en_cours', 'a_signer', 'annulee'):
                    raise UserError(_("L'OT externalisé ne peut être clôturé qu'une fois sa commande approuvée (RG-10.3)."))
                o._reception_service()
            o._sortie_pieces()
            vals = {'state': 'cloture', 'date_cloture': fields.Date.context_today(self)}
            if not o.duree_arret and o.date_debut and o.type == 'correctif':
                vals['duree_arret'] = (fields.Datetime.now() - o.date_debut).total_seconds() / 3600.0
            o.write(vals)
            o.plan_id.executer(o)   # avant le relevé : sinon le plan, encore « proche », générerait un nouvel OT
            if o.compteur_cloture and o.compteur_cloture > o.machine_id.compteur_heures:
                self.env['ka.mnt.releve'].create({'equipement_id': o.machine_id.id, 'type': 'heures',
                                                  'valeur': o.compteur_cloture, 'origine': o.name})
            o.machine_id.filtered(lambda m: m.state == 'arret').write({'state': 'service'})
            o.demande_id.filtered(lambda d: d.state != 'cloture').write({'state': 'cloture'})
            o._imputer()

    def _reception_service(self):
        """La clôture de l'OT vaut réception de la prestation : quantités reçues = commandées (pas de bon physique)."""
        cmd = self.commande_id
        po = cmd.po_id
        for l in po.order_line:
            if l.product_id.type == 'service':
                l.qty_received = l.product_qty
        for picking in po.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
            for m in picking.move_ids:
                m.quantity = m.product_uom_qty
            picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
        cmd.state = 'recue'
        lib = _('Prestation %s') % cmd.name
        if not self.ligne_ids.filtered(lambda l: l.type == 'sous_traitance'):
            self.write({'ligne_ids': [Command.create({'type': 'sous_traitance', 'detail': lib, 'quantite': 1,
                                                      'prix_unitaire': cmd.total})]})

    def _sortie_pieces(self):
        """Sortie du magasin de pièces (module 2) vers l'emplacement de consommation maintenance."""
        lignes = self.ligne_ids.filtered(lambda l: l.type == 'piece' and l.product_id and l.product_id.is_storable
                                         and not l.move_id and l.quantite > 0)
        if not lignes:
            return
        wh = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        dest = self.env.ref('kode_agri_maintenance.location_conso_mnt')
        for l in lignes:
            vals = {'product_id': l.product_id.id, 'product_uom_qty': l.quantite, 'product_uom': l.product_id.uom_id.id,
                    'location_id': wh.lot_stock_id.id, 'location_dest_id': dest.id, 'origin': self.name}
            if 'name' in self.env['stock.move']._fields:   # libellé obligatoire selon la version
                vals['name'] = '%s — %s' % (self.name, l.product_id.display_name)
            move = self.env['stock.move'].create(vals)
            move._action_confirm()
            move._action_assign()
            move.quantity = l.quantite
            move.picked = True
            move._action_done()
            l.move_id = move

    def _imputer(self):
        """Coût de maintenance imputé au coût d'usinage (section USINAGE du module 9), croisé avec l'axe équipement."""
        for o in self.filtered(lambda x: not x.imputation_faite and x.cout_total):
            usinage = section(self.env, 'USINAGE')
            if not usinage:
                continue
            vals = {'name': '%s — %s' % (o.name, o.machine_id.name), 'date': o.date_cloture, 'amount': -o.cout_total,
                    'company_id': self.env.company.id, 'account_id': usinage.id, plan_col(plan_de(usinage)): usinage.id}
            equip = o.machine_id.analytic_id
            if equip and plan_col(plan_de(equip)) != 'account_id':
                vals[plan_col(plan_de(equip))] = equip.id
            self.env['account.analytic.line'].create(vals)
            o.imputation_faite = True

    def action_annuler(self):
        for o in self:
            if o.state == 'cloture':
                raise UserError(_('Un OT clôturé ne peut pas être annulé.'))
            o.state = 'annule'

    def action_open_machine(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.mnt.equipement', 'res_id': self.machine_id.id, 'view_mode': 'form'}

    def action_open_commande(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.commande', 'res_id': self.commande_id.id, 'view_mode': 'form'}

    def action_open_da(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.da', 'res_id': self.da_id.id, 'view_mode': 'form'}


class KaMntOtLigne(models.Model):
    """Ligne d'OT : main-d'œuvre (temps × technicien), pièce ou consommable, prestation sous-traitée, opération de gamme."""
    _name = 'ka.mnt.ot.ligne'
    _description = "Ligne d'ordre de travail"
    _order = 'sequence, id'

    ot_id = fields.Many2one('ka.mnt.ot', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    type = fields.Selection([('main_oeuvre', "Main-d'œuvre"), ('piece', 'Pièce'), ('sous_traitance', 'Sous-traitance'),
                             ('operation', 'Opération')], string='Type', required=True, default='piece')
    ligne = fields.Char(compute='_compute_ligne', string='Ligne')
    detail = fields.Char(string='Détail')
    technicien_id = fields.Many2one('ka.rh.employe', string='Technicien')
    product_id = fields.Many2one('product.product', string='Pièce')
    quantite = fields.Float(string='Quantité', digits=(10, 2), default=1.0)
    quantite_txt = fields.Char(compute='_compute_ligne', string='Quantité')
    currency_id = fields.Many2one(related='ot_id.currency_id')
    prix_unitaire = fields.Monetary(string='Prix unitaire / taux', compute='_compute_prix', store=True, readonly=False)
    cout = fields.Monetary(compute='_compute_cout', string='Coût', store=True)
    move_id = fields.Many2one('stock.move', string='Sortie magasin', readonly=True, copy=False)

    @api.depends('type', 'product_id', 'technicien_id')
    def _compute_prix(self):
        for l in self:
            if l.type == 'piece' and l.product_id:
                l.prix_unitaire = l.product_id.standard_price
            elif l.type == 'main_oeuvre':
                l.prix_unitaire = l.ot_id.equipe_id.taux_horaire or float(
                    self.env['ir.config_parameter'].sudo().get_param('kode_agri_maintenance.taux_horaire', 20000))

    @api.depends('quantite', 'prix_unitaire', 'type')
    def _compute_cout(self):
        for l in self:
            l.cout = 0.0 if l.type == 'operation' else l.quantite * l.prix_unitaire

    @api.depends('type', 'product_id', 'technicien_id', 'quantite')
    def _compute_ligne(self):
        for l in self:
            if l.type == 'main_oeuvre':
                l.ligne = _("Main-d'œuvre")
                l.quantite_txt = ('%g h' % l.quantite).replace('.', ',')
            elif l.type == 'piece':
                l.ligne = _('Pièce %s') % (l.product_id.default_code or l.product_id.name or '')
                l.quantite_txt = ('%g' % l.quantite).replace('.', ',')
            else:
                l.ligne = dict(self._fields['type'].selection)[l.type]
                l.quantite_txt = ('%g' % l.quantite).replace('.', ',') if l.type == 'sous_traitance' else ''

    @api.onchange('technicien_id', 'type', 'quantite')
    def _onchange_detail(self):
        if self.type == 'main_oeuvre' and self.technicien_id:
            self.detail = ('Technicien × %g h' % self.quantite).replace('.', ',')
        elif self.type == 'piece' and self.product_id and not self.detail:
            self.detail = self.product_id.name
