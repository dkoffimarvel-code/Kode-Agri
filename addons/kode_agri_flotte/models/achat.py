from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.addons.kode_agri_gestion.models.common import plan_col, plan_de, section

# activité analytique (module 9) selon l'usage du véhicule : collecte → coût d'achat FDT, liaison → mise à FOB…
SECTION_USAGE = {'collecte': 'ACH_FDT', 'liaison': 'FOB', 'manutention': 'USINAGE', 'cour': 'USINAGE'}


class KaFloAchat(models.AbstractModel):
    """Circuit achats des prestations externes de la flotte (§ 11.2.1) : c'est toujours l'OT qui part en premier.
    Fournisseur ponctuel : demande d'achat déjà validée → appel d'offre → commande (RG-11.2) ; prestataire sous
    contrat-cadre : l'OT appelle directement la commande existante. La clôture exige la commande approuvée et déclenche
    la réception automatique, constat de service fait (RG-11.3)."""
    _name = 'ka.flo.achat'
    _description = 'Prestation externe de la flotte'

    externe = fields.Boolean(string='Intervention externe', tracking=True)
    prestataire_id = fields.Many2one('res.partner', string='Prestataire / garage')
    commande_cadre = fields.Boolean(string='Prestataire sous contrat-cadre')
    da_id = fields.Many2one('ka.da', string="Demande d'achat", readonly=True, copy=False)
    ao_id = fields.Many2one('ka.ao', string="Appel d'offre", compute='_compute_ka_achat')
    commande_id = fields.Many2one('ka.commande', string='Commande', copy=False)
    commande_state = fields.Selection(related='commande_id.state', string='Statut de la commande')
    facture_txt = fields.Char(compute='_compute_ka_achat', string='Facturation')

    @api.depends('da_id.ao_ids', 'commande_id.facture_ids.state')
    def _compute_ka_achat(self):
        for r in self:
            r.ao_id = r.da_id.ao_ids[:1]
            f = r.commande_id.facture_ids
            r.facture_txt = ', '.join('%s (%s)' % (x.name, dict(x._fields['state'].selection).get(x.state)) for x in f) if f else (
                _('En attente de la facture fournisseur') if r.commande_id else '')

    def _ka_site(self):
        return self.env['ka.site'].search([], limit=1)

    def _ka_lancer_achat(self, objet, montant_estime):
        """Déclenche le circuit achats depuis l'OT qualifié « intervention externe »."""
        self.ensure_one()
        if self.commande_id:
            raise UserError(_('Une commande est déjà rattachée : %s.') % self.commande_id.name)
        if self.commande_cadre:   # contrat-cadre : pas de demande d'achat ni d'appel d'offre
            cadre = self.env['ka.commande'].search([('partner_id', '=', self.prestataire_id.id),
                                                    ('state', 'in', ('signee', 'recue'))], order='date_commande desc', limit=1)
            if not cadre:
                raise UserError(_('Aucune commande-cadre signée pour %s.') % (self.prestataire_id.name or '?'))
            self.commande_id = cadre
            return cadre
        if not self._ka_site():
            raise UserError(_("Aucun site n'est paramétré (données de structure, module 2)."))
        service = self.env.ref('kode_agri_maintenance.product_prestation_mnt').product_variant_id
        da = self.env['ka.da'].create({
            'objet': objet, 'site_id': self._ka_site().id, 'demandeur': self.env.user.name,
            'partner_id': self.prestataire_id.id or False, 'date_besoin': fields.Date.context_today(self),
            'line_ids': [Command.create({'product_id': service.id, 'designation': objet, 'qty': 1, 'uom_id': service.uom_id.id,
                                         'montant': montant_estime})]})
        da.write({'state': 'signee'})   # le diagnostic de l'OT vaut justification (RG-11.2)
        self.da_id = da
        da.action_demande_prix()       # appel d'offre pour challenger la cotation initiale
        return da

    def _ka_controler_commande(self):
        """RG-11.3 : clôture conditionnée à la commande approuvée ; récupère la commande issue de l'appel d'offre."""
        self.ensure_one()
        if not self.externe:
            return
        if self.ao_id and not self.commande_id:
            self.commande_id = self.ao_id.commande_id
        if not self.commande_id or self.commande_id.state in ('en_cours', 'a_signer', 'annulee'):
            raise UserError(_("Une intervention externe ne peut être clôturée que si sa commande d'achat est approuvée (RG-11.3)."))

    def _ka_reception_auto(self, libelle):
        """Réception automatique de la commande à la clôture (constat de service fait)."""
        cmd = self.commande_id
        if not cmd or self.commande_cadre:
            return
        for l in cmd.po_id.order_line.filtered(lambda x: x.product_id.type == 'service'):
            l.qty_received = l.product_qty
        for p in cmd.po_id.picking_ids.filtered(lambda x: x.state not in ('done', 'cancel')):
            for m in p.move_ids:
                m.quantity = m.product_uom_qty
            p.with_context(skip_backorder=True, skip_sms=True).button_validate()
        cmd.state = 'recue'
        cmd.message_post(body=_('Réception automatique à la clôture de %s (RG-11.3).') % libelle)

    def _ka_imputer(self, vehicule, montant, libelle, date):
        """Ligne analytique : activité selon l'usage du véhicule (module 9), croisée avec l'axe équipement du véhicule."""
        sec = section(self.env, SECTION_USAGE.get(vehicule.categorie, 'USINAGE'))
        if not sec or not montant:
            return
        vals = {'name': libelle, 'date': date, 'amount': -montant, 'company_id': self.env.company.id,
                'account_id': sec.id, plan_col(plan_de(sec)): sec.id}
        if vehicule.analytic_id and plan_col(plan_de(vehicule.analytic_id)) != 'account_id':
            vals[plan_col(plan_de(vehicule.analytic_id))] = vehicule.analytic_id.id
        self.env['account.analytic.line'].create(vals)
