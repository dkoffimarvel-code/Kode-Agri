import math
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import (ARMATEURS, ARMATEURS_BMC, DETENTION_JOURS, PAIEMENTS, POIDS_COLIS, TAUX_CHANGE_EUR_XOF,
                     ka_param)
from .contrat import fmt_int

TAUX_TCT = 0.1            # % du prix de référence CAF (paramétrable)
TAUX_DROITS = 5.0          # droits et taxes de base, en % du prix CAF (paramétrable)
TS_DOUANE = 20000.0        # forfait par dossier
TAUX_AGIOS = 0.2           # % des droits de douane et taxes
TAUX_GESTION_CREDIT = 0.4  # % des droits de douane et taxes
PARAFISCALITE_KG = 22.0    # FCFA / kg du poids du contrat


class KaScontrat(models.Model):
    """Sous-contrat = une expédition (un navire) : instructions client, booking, jalons, export, port, départ."""
    _name = 'ka.sous.contrat'
    _description = 'Sous-contrat'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° sous-contrat', readonly=True, copy=False, default='Nouveau')
    contrat_id = fields.Many2one('ka.contrat', string='Commande ouverte 1', required=True, ondelete='restrict')
    contrat2_id = fields.Many2one('ka.contrat', string='Commande ouverte 2')
    partner_id = fields.Many2one(related='contrat_id.partner_id', string='Client', store=True)
    tracabilite = fields.Selection(related='contrat_id.tracabilite', string='Statut de traçabilité', store=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Usine', required=True)
    product_id = fields.Many2one('product.product', string='Grade chargé', required=True,
                                 domain=[('default_code', 'in', ('TSR10', 'TSR20', 'OFFSPECS'))])
    poids_kg = fields.Float(string='Poids à livrer (kg)', digits=(12, 0), required=True)
    conditionnement = fields.Selection([('palette', 'Palettisé'), ('vrac', 'Vrac')], string='Conditionnement',
                                       required=True, default='palette')
    marquage = fields.Char(string='Marquage palette', required=True)
    remarques = fields.Text(string='Autres remarques client')
    country_id = fields.Many2one('res.country', string='Pays de destination', required=True)
    doc_phyto_requis = fields.Boolean(string='Document phyto')
    certificat_garantie = fields.Boolean(string='Certificat de garantie')
    paiement = fields.Selection(PAIEMENTS, string='Condition de paiement', required=True, default='prefinancement')
    banque = fields.Char(string='Banque de domiciliation')
    currency_id = fields.Many2one(related='contrat_id.currency_id')
    company_currency_id = fields.Many2one(related='contrat_id.company_currency_id')
    prix_t = fields.Float(related='contrat_id.prix_t', string='Prix', digits=(10, 0))
    montant = fields.Monetary(string='Montant en devise', compute='_compute_montant', store=True)
    contre_valeur = fields.Monetary(string='Contre-valeur', compute='_compute_montant', store=True,
                                    currency_field='company_currency_id')
    # booking
    armateur = fields.Selection(ARMATEURS, string='Armateur', required=True)
    transitaire_id = fields.Many2one('res.partner', string='Transitaire', required=True)
    navire = fields.Char(string='Navire souhaité', required=True)
    voyage_no = fields.Char(string='N° voyage', required=True)
    booking = fields.Char(string='N° booking')
    bmc = fields.Char(string='N° BMC')
    bmc_requis = fields.Boolean(compute='_compute_bmc')
    date_booking_valide = fields.Date(string='Booking validé le', readonly=True)
    date_bmc = fields.Date(string='Date du BMC', compute='_compute_bmc')
    date_instructions = fields.Date(string='Instructions saisies le', default=fields.Date.context_today)
    date_embarquement_prevue = fields.Date(string='Embarquement prévu', required=True)
    date_embarquement_maj = fields.Date(string="Mise à jour de l'embarquement")
    date_fermeture_navire = fields.Date(string='Fermeture du navire', required=True)
    limite_booking = fields.Char(compute='_compute_limite_booking', string='Limite de booking')
    info_booking = fields.Char(compute='_compute_limite_booking')
    spec_ids = fields.One2many(related='contrat_id.spec_ids', string='Spécifications')
    frais_ids = fields.One2many('ka.sc.frais', 'sc_id', string='Frais supplémentaires')
    conteneur_ids = fields.One2many('ka.conteneur', 'sous_contrat_id', string='Conteneurs')
    # indicateurs
    nb_conteneurs = fields.Integer(compute='_compute_kpi', string='Conteneurs')
    conteneurs_txt = fields.Char(compute='_compute_kpi', string='Conteneurs')
    nb_empotes = fields.Integer(compute='_compute_kpi', string='Empotés')
    poids_txt = fields.Char(compute='_compute_kpi', string='À livrer')
    # ordre de transit
    shipper = fields.Char(string='Shipper', default='EXAT SA')
    notify1 = fields.Char(string='Notify party 1')
    notify2 = fields.Char(string='Notify party 2')
    notify3 = fields.Char(string='Notify party 3')
    consignee = fields.Char(string='Consignee')
    consignee2 = fields.Char(string='Consignee 2')
    description_marchandise = fields.Text(string='Description de la marchandise')
    liasse_demandee = fields.Text(string='Liasse documentaire demandée',
                                  default="BL, certificat d'origine, certificat phytosanitaire, certificat d'analyse, liste de colisage")
    ot_numero = fields.Char(compute='_compute_ot', string='N° ordre de transit')
    navire_arrivee = fields.Char(compute='_compute_ot', string='Navire et arrivée')
    # jalons
    date_bl_impression = fields.Date(string='Impression du BL')
    date_depart_bateau = fields.Date(string='Départ du bateau')
    date_bl_reception = fields.Date(string='Réception du BL')
    date_docs_expedies = fields.Date(string='Expédition des documents')
    date_phyto_reception = fields.Date(string='Réception phyto')
    date_bae_reception = fields.Date(string='Réception du bon à embarquer')
    daex = fields.Char(string='Numéro DAEX')
    d6_numero = fields.Char(string='Numéro D6')
    d6_date = fields.Date(string='Date D6')
    ae_ec = fields.Char(string='Numéros AE / EC')
    # déclaration d'exportation
    decl_numero = fields.Char(string='N° déclaration')
    decl_date = fields.Date(string='Date de déclaration')
    prix_caf = fields.Monetary(compute='_compute_caf', string='Prix de référence CAF', currency_field='company_currency_id')
    droits_taxes = fields.Monetary(compute='_compute_caf', string='Droits et taxes (base)', currency_field='company_currency_id')
    decl_state = fields.Selection([('attente', 'En attente'), ('recue', 'Reçue'), ('dus', 'DUS générée'),
                                   ('complete', 'Complète')], default='attente', string='Statut déclaration')
    dus_ids = fields.One2many('ka.sc.achat', 'sc_id', string="Commande d'achat DUS", domain=[('type', '=', 'dus')])
    parafisc_ids = fields.One2many('ka.sc.achat', 'sc_id', string='Commande parafiscalité', domain=[('type', '=', 'parafisc')])
    dus_total = fields.Float(compute='_compute_dus_total', string='Total commande DUS', digits=(12, 0))
    po_dus_id = fields.Many2one('purchase.order', readonly=True, copy=False)
    po_parafisc_id = fields.Many2one('purchase.order', readonly=True, copy=False)
    # port
    bae_numero = fields.Char(string='N° BAE')
    bae_date = fields.Date(string='Date de réception du BAE')
    plateforme_transitaire = fields.Char(string='Plateforme transitaire')
    plateforme_armateur = fields.Char(string='Plateforme armateur')
    transporteur_id = fields.Many2one('res.partner', string='Transporteur')
    proprietaire_parc = fields.Char(string='Propriétaire du parc')
    transferts_txt = fields.Char(compute='_compute_kpi')
    # départ navire
    bl_numero = fields.Char(string='N° connaissement (BL)')
    date_depart_navire = fields.Date(string='Date de départ du navire')
    tous_embarques = fields.Boolean(string='Tous les colis embarqués', compute='_compute_kpi', store=True)
    embarques_txt = fields.Char(compute='_compute_kpi')
    doc_bl = fields.Boolean(string='connaissement')
    doc_colisage = fields.Boolean(string='liste de colisage')
    doc_analyse = fields.Boolean(string="certificat d'analyse qualité")
    doc_facture = fields.Boolean(string='facture client (émise à la clôture)', readonly=True)
    frais_declares = fields.Char(compute='_compute_kpi')
    po_transit_id = fields.Many2one('purchase.order', readonly=True, copy=False)
    invoice_id = fields.Many2one('account.move', readonly=True, copy=False)
    state = fields.Selection([('brouillon', 'Brouillon'), ('instructions', 'Instructions saisies'),
                              ('booke', 'Booking validé'), ('en_cours', 'En cours'), ('expedie', 'Expédié'),
                              ('cloture', 'Clôturé')], default='brouillon', string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        return "%s — ligne de programme de la commande ouverte %s" % (self.name, self.contrat_id.name or '')

    # ---- calculs -------------------------------------------------------------------------------------------
    @api.depends('poids_kg', 'prix_t', 'currency_id')
    def _compute_montant(self):
        for sc in self:
            sc.montant = sc.poids_kg / 1000.0 * sc.prix_t
            rate = 1.0
            if sc.currency_id and sc.currency_id != sc.company_currency_id:
                rate = sc.currency_id._get_conversion_rate(sc.currency_id, sc.company_currency_id, self.env.company,
                                                           fields.Date.context_today(sc))
                if sc.currency_id.name == 'EUR' and sc.company_currency_id.name == 'XOF' and abs(rate - 1.0) < 1e-6:
                    rate = TAUX_CHANGE_EUR_XOF
            sc.contre_valeur = sc.montant * rate

    @api.depends('dus_ids.montant')
    def _compute_dus_total(self):
        for sc in self:
            sc.dus_total = sum(sc.dus_ids.mapped('montant'))

    @api.depends('contre_valeur')
    def _compute_caf(self):
        for sc in self:
            sc.prix_caf = sc.contre_valeur
            sc.droits_taxes = round(sc.contre_valeur * TAUX_DROITS / 100.0)

    def capacite_kg(self):
        self.ensure_one()
        colis = ka_param(self.env, 'colis_vrac', 17.0) if self.conditionnement == 'vrac' else ka_param(self.env, 'colis_palette', 16.0)
        return colis * POIDS_COLIS

    def colis_par_conteneur(self):
        return int(self.capacite_kg() / POIDS_COLIS)

    @api.depends('armateur', 'date_booking_valide')
    def _compute_bmc(self):
        for sc in self:
            sc.bmc_requis = sc.armateur in ARMATEURS_BMC
            # RG-5.7 : la date du BMC est fixée à un jour après la validation du booking.
            sc.date_bmc = sc.date_booking_valide + timedelta(days=1) if sc.date_booking_valide and sc.bmc_requis else False

    @api.depends('date_instructions', 'date_embarquement_prevue', 'armateur')
    def _compute_limite_booking(self):
        """RG-5.6 : 48 h si les instructions sont saisies le mois de livraison, 7 jours le mois précédent."""
        for sc in self:
            d, e = sc.date_instructions, sc.date_embarquement_prevue
            if d and e and (d.year, d.month) == (e.year, e.month):
                sc.limite_booking = '48 h'
            else:
                sc.limite_booking = '7 jours'
            quand = 'le mois de livraison' if sc.limite_booking == '48 h' else 'le mois précédent la livraison'
            bmc = ("BMC requis par l'armateur %s : validation du booking + 1 jour." % sc.armateur) if sc.bmc_requis else 'BMC non requis.'
            sc.info_booking = "Instructions saisies %s : booking sous %s. %s « Scinder » sert aux conteneurs restés à quai (§ 5.6)." % (
                quand, sc.limite_booking, bmc)

    @api.depends('poids_kg', 'conteneur_ids.state', 'conteneur_ids.transfert_effectue', 'conteneur_ids.embarque',
                 'conditionnement', 'frais_ids')
    def _compute_kpi(self):
        for sc in self:
            cap = sc.capacite_kg() if sc.conditionnement else POIDS_COLIS * 16
            n = math.ceil(sc.poids_kg / cap) if cap and sc.poids_kg else 0
            sc.nb_conteneurs = n
            sc.conteneurs_txt = '%s (%s balles)' % (n, fmt_int(n * sc.colis_par_conteneur() * 36)) if sc.conditionnement else str(n)
            sc.poids_txt = '%s kg' % fmt_int(sc.poids_kg)
            ctns = sc.conteneur_ids
            sc.nb_empotes = len(ctns.filtered(lambda c: c.state in ('empote', 'au_port', 'embarque')))
            tr = len(ctns.filtered('transfert_effectue'))
            sc.transferts_txt = '%s / %s transférés' % (tr, len(ctns))
            emb = len(ctns.filtered('embarque'))
            sc.embarques_txt = '%s / %s embarqués' % (emb, len(ctns))
            sc.tous_embarques = bool(ctns) and emb == len(ctns)
            sc.frais_declares = 'oui' if sc.frais_ids else 'non'

    @api.depends('name', 'navire', 'date_embarquement_prevue')
    def _compute_ot(self):
        for sc in self:
            sc.ot_numero = 'OT-' + (sc.name or '').replace('SC-', '')
            d = sc.date_embarquement_prevue.strftime('%d/%m/%Y') if sc.date_embarquement_prevue else ''
            sc.navire_arrivee = ('%s — %s' % (sc.navire, d)).strip(' —')

    @api.onchange('contrat_id')
    def _onchange_contrat(self):
        c = self.contrat_id
        if c:
            self.product_id = c.product_id
            self.conditionnement = 'vrac' if c.emballage == 'vrac' else 'palette'
            self.paiement = c.paiement or self.paiement
            self.warehouse_id = c.warehouse_id
            self.consignee = self.consignee or c.partner_id.name
            self.notify1 = self.notify1 or c.partner_id.name
            self.description_marchandise = 'Caoutchouc naturel %s' % (c.product_id.default_code or '')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                contrat = self.env['ka.contrat'].browse(vals.get('contrat_id'))
                rang = self.search_count([('contrat_id', '=', contrat.id)]) + 1
                vals['name'] = 'SC-%s-%02d' % ((contrat.name or 'CV-0000').replace('CV-', ''), rang)
        return super().create(vals_list)

    # ---- workflow ------------------------------------------------------------------------------------------------
    def write(self, vals):
        res = super().write(vals)
        if 'decl_numero' in vals or 'decl_date' in vals:
            self.filtered(lambda s: s.decl_numero and s.decl_date and s.decl_state == 'attente').write({'decl_state': 'recue'})
        return res

    def action_instructions(self):
        self.filtered(lambda s: s.state == 'brouillon').write({'state': 'instructions'})

    def action_valider_booking(self):
        for sc in self:
            if not sc.booking:
                raise UserError(_('Renseignez le N° de booking.'))
            if sc.bmc_requis and not sc.bmc:
                raise UserError(_("Le BMC est obligatoire pour l'armateur %s (RG-5.7).") % sc.armateur)
            sc.write({'state': 'booke', 'date_booking_valide': fields.Date.context_today(sc)})

    def action_ordre_transit(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.sous.contrat', 'res_id': self.id,
                'view_mode': 'form', 'views': [(self.env.ref('kode_agri_vente.view_ka_sc_transit_form').id, 'form')]}

    def action_retour_sc(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.sous.contrat', 'res_id': self.id,
                'view_mode': 'form', 'views': [(self.env.ref('kode_agri_vente.view_ka_sc_form').id, 'form')]}

    def action_envoyer_email(self):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Ordre de transit'), 'type': 'success', 'sticky': False,
                           'message': _('Ordre de transit envoyé au transitaire.')}}

    def action_imprimer(self):
        return self.action_envoyer_email()

    def action_scinder(self):
        """§ 5.6 : les conteneurs laissés à quai passent sur un nouveau sous-contrat à nouveau booking."""
        self.ensure_one()
        restes = self.conteneur_ids.filtered(lambda c: not c.embarque)
        if not restes:
            raise UserError(_('Aucun conteneur laissé à quai : rien à scinder.'))
        poids_restant = sum(c.poids_colis() for c in restes)
        nouveau = self.copy({'poids_kg': poids_restant, 'booking': False, 'bmc': False,
                             'date_booking_valide': False, 'state': 'instructions'})
        restes.write({'sous_contrat_id': nouveau.id})
        self.poids_kg -= poids_restant
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.sous.contrat', 'res_id': nouveau.id,
                'view_mode': 'form', 'views': [(self.env.ref('kode_agri_vente.view_ka_sc_form').id, 'form')]}

    def action_cloturer_jalons(self):
        for sc in self:
            if not sc.date_depart_bateau:
                raise UserError(_('Renseignez la date de départ du bateau.'))
            sc.state = 'expedie'

    # ---- déclaration d'exportation (§ 5.4.4) -------------------------------------------------------------------
    def action_decl_recue(self):
        for sc in self:
            if not (sc.decl_numero and sc.decl_date):
                raise UserError(_("Renseignez le numéro et la date de déclaration d'exportation."))
            sc.decl_state = 'recue'

    def _fournisseur_douane(self):
        return self.env.ref('kode_agri_vente.partner_douane')

    def _produit(self, xmlid):
        return self.env.ref('kode_agri_vente.' + xmlid)

    def _creer_po(self, lignes):
        po = self.env['purchase.order'].create({
            'partner_id': self._fournisseur_douane().id, 'origin': self.name,
            'order_line': [Command.create({'product_id': p.id, 'name': lib, 'product_qty': 1, 'price_unit': montant})
                           for p, lib, montant in lignes]})
        return po

    def action_generer_dus(self):
        """Bouton « Générer DUS » : TCT, TS douane, agios trésor, gestion crédit."""
        for sc in self:
            if sc.decl_state == 'attente':
                raise UserError(_("Enregistrez d'abord la déclaration reçue du transitaire."))
            caf, droits = sc.prix_caf, sc.droits_taxes
            lignes = [(sc._produit('product_tct'), 'TCT', round(caf * TAUX_TCT / 100.0)),
                      (sc._produit('product_ts_douane'), 'TS douane', TS_DOUANE),
                      (sc._produit('product_agios'), 'Agios trésor', round(droits * TAUX_AGIOS / 100.0)),
                      (sc._produit('product_gestion_credit'), 'Gestion crédit', round(droits * TAUX_GESTION_CREDIT / 100.0))]
            sc.po_dus_id = sc._creer_po(lignes)
            sc.dus_ids.unlink()
            bases = {'TCT': ('Prix de référence CAF', 'Paramétré'), 'TS douane': ('Forfait par dossier', '20 000 FCFA'),
                     'Agios trésor': ('Droits de douane et taxes', '0,2 %'), 'Gestion crédit': ('Droits de douane et taxes', '0,4 %')}
            sc.dus_ids = [Command.create({'type': 'dus', 'ligne': lib, 'base': bases[lib][0], 'taux': bases[lib][1],
                                          'montant': m}) for _p, lib, m in lignes]
            sc.decl_state = 'dus' if not sc.po_parafisc_id else 'complete'

    def action_generer_parafiscalite(self):
        """Bouton « Générer Parafiscalité » : 22 FCFA par kg du poids du contrat."""
        for sc in self:
            if sc.decl_state == 'attente':
                raise UserError(_("Enregistrez d'abord la déclaration reçue du transitaire."))
            montant = round(sc.poids_kg * PARAFISCALITE_KG)
            sc.po_parafisc_id = sc._creer_po([(sc._produit('product_parafiscalite'), 'Redevance parafiscale export', montant)])
            sc.parafisc_ids.unlink()
            sc.parafisc_ids = [Command.create({'type': 'parafisc', 'ligne': 'Redevance parafiscale export',
                                          'base': 'Poids du contrat (%s kg)' % fmt_int(sc.poids_kg),
                                          'taux': '22 FCFA/kg', 'montant': montant})]
            sc.decl_state = 'complete' if sc.po_dus_id else 'dus'

    # ---- transfert vers le port (§ 5.5) --------------------------------------------------------------------------
    def action_transferer_port(self):
        """RG-5.20 : transfert des conteneurs sélectionnés et génération des deux réceptions de prestations."""
        for sc in self:
            a_transferer = sc.conteneur_ids.filtered(lambda c: c.date_entree_port and not c.transfert_effectue)
            if not a_transferer:
                raise UserError(_("Renseignez la date d'entrée au port des conteneurs à transférer."))
            port = self.env.ref('kode_agri_vente.loc_port')
            for ctn in a_transferer:
                ctn._transferer_colis(port)
                ctn.write({'transfert_effectue': True, 'state': 'au_port'})
            transporteur = sc.transporteur_id or self.env.ref('kode_agri_vente.partner_douane')
            lignes = [(sc._produit('product_stockage_franchise'), 'Stockage franchise — transfert vers le port', 0.0),
                      (sc._produit('product_forfait_franchise'), 'Forfait de franchise du terre-plein', 0.0)]
            for ctn in a_transferer:
                depasse = ctn.jours_hors_franchise()
                if depasse:
                    lignes.append((sc._produit('product_stockage_hors_franchise'),
                                   'Stockage hors franchise %s (%s j)' % (ctn.serie, depasse), 0.0))
            self.env['purchase.order'].create({
                'partner_id': transporteur.id, 'origin': sc.name,
                'order_line': [Command.create({'product_id': p.id, 'name': lib, 'product_qty': 1, 'price_unit': m})
                               for p, lib, m in lignes]})
            sc.state = 'en_cours' if sc.state in ('booke', 'instructions') else sc.state

    # ---- départ navire et clôture (§ 5.6) ---------------------------------------------------------------------------
    def action_valider_livraison(self):
        """Valide le BL vente à la date d'embarquement et crée la réception des frais de transit (RG-5.21)."""
        for sc in self:
            if not sc.bl_numero or not sc.date_depart_navire:
                raise UserError(_('Renseignez le N° de connaissement et la date de départ du navire.'))
            if not sc.tous_embarques:
                raise UserError(_('Tous les colis ne sont pas embarqués : scindez le sous-contrat (§ 5.6).'))
            sc.conteneur_ids.write({'state': 'embarque', 'embarque': True})
            lignes = [(sc._produit('product_frais_transit'), 'Frais de transit %s' % sc.name, 0.0)]
            lignes += [(sc._produit('product_frais_transit'), f.libelle, f.montant) for f in sc.frais_ids]
            sc.po_transit_id = self.env['purchase.order'].create({
                'partner_id': sc.transitaire_id.id, 'origin': sc.name,
                'order_line': [Command.create({'product_id': p.id, 'name': lib, 'product_qty': 1, 'price_unit': m})
                               for p, lib, m in lignes]})
            sc.write({'date_depart_bateau': sc.date_depart_navire, 'state': 'expedie', 'doc_bl': True})

    def action_liste_colisage(self):
        self.write({'doc_colisage': True})
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Liste de colisage'), 'type': 'success', 'sticky': False,
                           'message': _('Liste de colisage éditée.')}}

    def action_generer_facture(self):
        """Facture client export en devise, établie par la comptabilité après le départ du navire."""
        for sc in self:
            if sc.state not in ('expedie', 'cloture'):
                raise UserError(_("Validez la livraison (BL vente) avant de facturer."))
            if sc.invoice_id:
                continue
            move = self.env['account.move'].create({
                'move_type': 'out_invoice', 'partner_id': sc.partner_id.id, 'invoice_origin': sc.name,
                'currency_id': sc.currency_id.id, 'invoice_date': sc.date_depart_navire,
                'invoice_line_ids': [Command.create({'product_id': sc.product_id.id, 'name': '%s — %s' % (
                    sc.product_id.display_name, sc.name), 'quantity': sc.poids_kg / 1000.0, 'price_unit': sc.prix_t})]})
            sc.write({'invoice_id': move.id, 'doc_facture': True})

    def action_cloturer_dossier(self):
        """RG-5.14 : le dossier ne se clôture que si tous les documents requis sont livrés."""
        for sc in self:
            manquants = [lbl for lbl, ok in (('connaissement', sc.doc_bl), ('liste de colisage', sc.doc_colisage),
                                              ("certificat d'analyse qualité", sc.doc_analyse)) if not ok]
            if manquants:
                raise UserError(_('Documents non livrés au client : %s') % ', '.join(manquants))
            if not sc.invoice_id:
                sc.action_generer_facture()
            sc.state = 'cloture'


class KaScFrais(models.Model):
    _name = 'ka.sc.frais'
    _description = 'Frais supplémentaires du sous-contrat'

    sc_id = fields.Many2one('ka.sous.contrat', required=True, ondelete='cascade')
    libelle = fields.Char(string='Libellé', required=True, help='Ex. changement de navire')
    montant = fields.Float(string='Montant (FCFA)', digits=(12, 0))


class KaScAchat(models.Model):
    _name = 'ka.sc.achat'
    _description = "Ligne de commande d'achat générée (DUS / parafiscalité)"
    _order = 'type, id'

    sc_id = fields.Many2one('ka.sous.contrat', required=True, ondelete='cascade')
    type = fields.Selection([('dus', 'DUS'), ('parafisc', 'Parafiscalité')], required=True)
    ligne = fields.Char(string='Ligne')
    base = fields.Char(string='Base de calcul')
    taux = fields.Char(string='Taux / paramètre')
    montant = fields.Float(string='Montant', digits=(12, 0))
