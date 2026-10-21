from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.kode_agri_maintenance.models.equipement import nb

TYPES = [('camion', 'Camion'), ('4x4', '4×4'), ('liaison', 'Véhicule de liaison'), ('chariot', 'Chariot élévateur'),
         ('chargeur', 'Chargeur'), ('engin', 'Engin de cour')]
USAGES = [('collecte', 'Collecte fond de tasse'), ('liaison', 'Liaison'), ('manutention', 'Manutention usine'),
          ('cour', 'Cour')]
DOCS = [('carte_grise', 'Carte grise'), ('assurance', 'Assurance'), ('visite_technique', 'Visite technique'),
        ('vignette', 'Vignette'), ('autorisation', 'Autorisation de transport'), ('autre', 'Autre')]
ALERTE_JOURS = 30


def dec(x, n=1):
    return ('%.*f' % (n, x or 0.0)).replace('.', ',')


class KaFloVehicule(models.Model):
    """Fiche véhicule ou engin (§ 11.1) : identité, usage, compteur (kilométrage ou heures-moteur), documents
    réglementaires, conducteur, immobilisation (module 3) et centre de coût."""
    _name = 'ka.flo.vehicule'
    _description = 'Véhicule'
    _inherit = ['ka.document', 'mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Immatriculation', required=True, tracking=True)
    libelle = fields.Char(string='Libellé', help='Ex. Camion collecte')
    type = fields.Selection(TYPES, string='Type', required=True, default='camion')
    categorie = fields.Selection(USAGES, string="Catégorie d'usage", required=True, default='collecte')
    marque = fields.Char(string='Marque')
    modele = fields.Char(string='Modèle')
    marque_modele = fields.Char(compute='_compute_txt', string='Marque / modèle')
    annee = fields.Integer(string='Année de mise en circulation')
    unite_compteur = fields.Selection([('km', 'Kilométrage'), ('h', 'Heures-moteur')], string='Compteur', default='km',
                                      required=True)
    odometre = fields.Float(string='Compteur', digits=(12, 0), tracking=True)
    compteur_txt = fields.Char(compute='_compute_txt', string='Compteur')
    charge_utile = fields.Float(string='Charge utile (t)', digits=(6, 1))
    capacite_levage = fields.Float(string='Capacité de levage (t)', digits=(6, 1))
    capacite_txt = fields.Char(compute='_compute_txt', string='Charge utile')
    conducteur_id = fields.Many2one('ka.rh.employe', string='Conducteur affecté', tracking=True)
    conducteur_nom = fields.Char(related='conducteur_id.name', string='Conducteur')
    immo_id = fields.Many2one('ka.immo', string='Immobilisation')
    analytic_id = fields.Many2one('account.analytic.account', string='Centre de coût (axe équipement)')
    zone_id = fields.Many2one('account.analytic.account', string='Zone de collecte (analytique)')
    equipe_id = fields.Many2one('ka.mnt.equipe', string='Atelier interne')
    document_ids = fields.One2many('ka.flo.document', 'vehicule_id', string='Documents réglementaires')
    plan_ids = fields.One2many('ka.flo.plan', 'vehicule_id', string="Plans d'entretien")
    entretien_ids = fields.One2many('ka.flo.entretien', 'vehicule_id', string='Entretiens')
    plein_ids = fields.One2many('ka.flo.plein', 'vehicule_id', string='Pleins')
    affectation_ids = fields.One2many('ka.flo.affectation', 'vehicule_id', string='Affectations')
    releve_ids = fields.One2many('ka.flo.releve', 'vehicule_id', string='Relevés de compteur')
    incident_ids = fields.One2many('ka.flo.incident', 'vehicule_id', string='Incidents')
    conso_moyenne = fields.Float(compute='_compute_conso', string='Consommation moyenne (L/100 km)', digits=(6, 2))
    conso_txt = fields.Char(compute='_compute_conso', string='Conso moy.')
    documents_echus = fields.Boolean(compute='_compute_docs', string='Document obligatoire échu', search='_search_echus')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    # coût de revient de l'année en cours (§ 11.6)
    cout_carburant = fields.Monetary(compute='_compute_couts', string='Carburant')
    cout_entretien = fields.Monetary(compute='_compute_couts', string='Entretien et réparations')
    cout_pneus = fields.Monetary(compute='_compute_couts', string='Pneumatiques et consommables')
    cout_amortissement = fields.Monetary(compute='_compute_couts', string='Amortissement')
    cout_assurance = fields.Monetary(compute='_compute_couts', string='Assurance et taxes')
    cout_total = fields.Monetary(compute='_compute_couts', string='Coût total')
    distance = fields.Float(compute='_compute_couts', string='Distance / heures de l\'année', digits=(12, 0))
    cout_unitaire = fields.Monetary(compute='_compute_couts', string='Coût total / km (ou / heure)')
    cout_html = fields.Html(compute='_compute_couts', sanitize=False)
    titre = fields.Char(compute='_compute_txt')
    state = fields.Selection([('disponible', 'Disponible'), ('en_mission', 'En mission'), ('en_entretien', 'En entretien'),
                              ('immobilise', 'Immobilisé')], default='disponible', string='Statut', tracking=True)

    @api.depends('name', 'libelle')
    def _compute_display_name(self):
        for v in self:
            v.display_name = '%s — %s' % (v.name, v.libelle) if v.libelle else v.name

    def _ka_subtitle(self):
        self.ensure_one()
        usage = dict(USAGES).get(self.categorie, '')
        return '%s · usage %s' % (dict(TYPES).get(self.type, ''), usage[:1].lower() + usage[1:])

    @api.depends('marque', 'modele', 'odometre', 'unite_compteur', 'charge_utile', 'capacite_levage', 'libelle', 'name')
    def _compute_txt(self):
        for v in self:
            v.marque_modele = ' · '.join(x for x in (v.marque, v.modele) if x)
            v.compteur_txt = nb(v.odometre, v.unite_compteur)
            v.capacite_txt = ('%s t' % dec(v.charge_utile, 0 if v.charge_utile == int(v.charge_utile) else 1)) if v.charge_utile else (
                ('%s t (levage)' % dec(v.capacite_levage)) if v.capacite_levage else '')
            v.titre = ' '.join(x for x in (v.libelle, v.name) if x)

    @api.depends('plein_ids.quantite', 'plein_ids.km_parcourus')
    def _compute_conso(self):
        for v in self:
            pleins = v.plein_ids.filtered(lambda p: p.km_parcourus > 0)[:10]
            km = sum(pleins.mapped('km_parcourus'))
            v.conso_moyenne = 100.0 * sum(pleins.mapped('quantite')) / km if km else 0.0
            v.conso_txt = ('%s L/100' % dec(v.conso_moyenne)) if v.unite_compteur == 'km' else ('%s L/h' % dec(v.conso_moyenne / 100.0, 2))

    @api.depends('document_ids.echeance', 'document_ids.obligatoire')
    def _compute_docs(self):
        today = fields.Date.context_today(self)
        for v in self:
            v.documents_echus = any(d.obligatoire and d.echeance and d.echeance < today for d in v.document_ids)

    def _search_echus(self, operator, value):
        today = fields.Date.context_today(self)
        ids = self.env['ka.flo.document'].search([('obligatoire', '=', True), ('echeance', '<', today)]).vehicule_id.ids
        return [('id', 'in' if (operator == '=') == bool(value) else 'not in', ids)]

    def _compute_couts(self):
        today = fields.Date.context_today(self)
        debut, fin = date(today.year, 1, 1), date(today.year, 12, 31)
        for v in self:
            pleins = v.plein_ids.filtered(lambda p: debut <= p.date <= fin)
            ent = v.entretien_ids.filtered(lambda e: e.state == 'cloture' and e.date_cloture and debut <= e.date_cloture <= fin)
            v.cout_carburant = sum(pleins.mapped('cout'))
            v.cout_pneus = sum(ent.filtered(lambda e: e.type == 'pneumatiques').mapped('cout_total'))
            v.cout_entretien = sum(ent.filtered(lambda e: e.type != 'pneumatiques').mapped('cout_total'))
            v.cout_amortissement = sum(v.immo_id.plan_ids.filtered(lambda p: p.date and debut <= p.date <= fin).mapped('dotation')) \
                if v.immo_id else 0.0
            v.cout_assurance = sum(v.document_ids.filtered(lambda d: d.date_debut and debut <= d.date_debut <= fin).mapped('montant'))
            v.cout_total = v.cout_carburant + v.cout_entretien + v.cout_pneus + v.cout_amortissement + v.cout_assurance
            rel = v.releve_ids.filtered(lambda r: debut <= r.date <= fin)
            v.distance = (max(rel.mapped('valeur')) - min(rel.mapped('valeur'))) if len(rel) > 1 else 0.0
            v.cout_unitaire = v.cout_total / v.distance if v.distance else 0.0
            u = v.unite_compteur
            lignes = [('Carburant', 'Pleins et dotations (§ 11.3)', v.cout_carburant),
                      ('Entretien et réparations', "Ordres d'entretien (§ 11.2) ; factures rapprochées (§ 11.2.1)", v.cout_entretien),
                      ('Pneumatiques et consommables', 'Sorties magasin (module 2)', v.cout_pneus),
                      ('Amortissement', 'Immobilisation du véhicule (module 3)', v.cout_amortissement),
                      ('Assurance et taxes', 'Documents réglementaires (§ 11.4)', v.cout_assurance)]
            v.cout_html = ('<table class="o_ka_tbl"><thead><tr><th>Composante du coût</th><th>Source</th>'
                           '<th class="o_ka_num">%s</th></tr></thead><tbody>%s</tbody><tfoot><tr><td>Coût total / %s</td>'
                           '<td>%s %s parcourus</td><td class="o_ka_num">%s FCFA</td></tr></tfoot></table>') % (
                today.year, ''.join('<tr><td>%s</td><td>%s</td><td class="o_ka_num">%s</td></tr>' % (a, b, nb(c)) for a, b, c in lignes),
                'km' if u == 'km' else 'heure', nb(v.distance), u, dec(v.cout_unitaire))

    @api.constrains('name')
    def _check_immat(self):
        for v in self:
            if self.search_count([('name', '=', v.name)]) > 1:
                raise ValidationError(_("L'immatriculation %s existe déjà.") % v.name)

    def maj_compteur(self, valeur, origine, jour=None):
        """Relevé de compteur (clôture d'entretien, plein, retour de tournée) : met à jour le kilométrage et déclenche les
        plans d'entretien (RG-11.1)."""
        for v in self.filtered(lambda x: valeur and valeur > x.odometre):
            self.env['ka.flo.releve'].create({'vehicule_id': v.id, 'valeur': valeur, 'origine': origine,
                                              'date': jour or fields.Date.context_today(self)})

    def verifier_disponibilite(self):
        """§ 11.4 : un véhicule dont un document obligatoire est échu est bloqué à l'affectation."""
        for v in self:
            echus = v.document_ids.filtered(lambda d: d.obligatoire and d.echeance and d.echeance < fields.Date.context_today(self))
            if echus:
                raise UserError(_('Véhicule %s bloqué : document échu (%s).') % (v.name, ', '.join(echus.mapped('type_txt'))))
            if v.state in ('en_entretien', 'immobilise'):
                raise UserError(_('Le véhicule %s est %s.') % (v.name, dict(self._fields['state'].selection)[v.state].lower()))

    def action_ordre_entretien(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.flo.entretien', 'view_mode': 'form',
                'context': {'default_vehicule_id': self.id, 'default_km_declenchement': self.odometre}}

    def action_releve(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Relevé de compteur'), 'res_model': 'ka.flo.releve',
                'view_mode': 'form', 'target': 'new', 'context': {'default_vehicule_id': self.id}}

    def action_open_pleins(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Pleins'), 'res_model': 'ka.flo.plein', 'view_mode': 'list,form',
                'domain': [('vehicule_id', '=', self.id)], 'context': {'default_vehicule_id': self.id}}

    def action_immobiliser(self):
        self.write({'state': 'immobilise'})

    def action_disponible(self):
        self.write({'state': 'disponible'})


class KaFloReleve(models.Model):
    _name = 'ka.flo.releve'
    _description = 'Relevé de compteur de véhicule'
    _order = 'date desc, valeur desc'

    vehicule_id = fields.Many2one('ka.flo.vehicule', string='Véhicule', required=True, ondelete='cascade')
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    valeur = fields.Float(string='Compteur', required=True, digits=(12, 0))
    origine = fields.Char(string='Origine', default='Saisie')

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        for r in recs:
            v = r.vehicule_id
            if r.valeur < v.odometre:
                raise UserError(_('Relevé %s inférieur au compteur actuel du véhicule %s (%s).') % (nb(r.valeur), v.name, nb(v.odometre)))
            v.odometre = r.valeur
        recs.vehicule_id.plan_ids.filtered(lambda p: p.state == 'actif').verifier_echeances()
        return recs


class KaFloDocument(models.Model):
    """Document réglementaire (§ 11.4) : échéance et alerte avant expiration ; un document obligatoire échu bloque
    l'affectation du véhicule."""
    _name = 'ka.flo.document'
    _description = 'Document réglementaire de véhicule'
    _order = 'echeance'

    vehicule_id = fields.Many2one('ka.flo.vehicule', string='Véhicule', required=True, ondelete='cascade')
    type = fields.Selection(DOCS, string='Document', required=True)
    type_txt = fields.Char(compute='_compute_statut', string='Document')
    reference = fields.Char(string='Référence')
    date_debut = fields.Date(string='Début de validité')
    echeance = fields.Date(string='Échéance')
    obligatoire = fields.Boolean(string='Obligatoire', default=True)
    currency_id = fields.Many2one(related='vehicule_id.currency_id')
    montant = fields.Monetary(string='Coût (prime, taxe)')
    fichier = fields.Binary(string='Pièce jointe', attachment=True)
    statut = fields.Selection([('valide', 'Valide'), ('proche', 'Échéance proche'), ('echu', 'Échu')],
                              compute='_compute_statut', string='Statut')

    @api.depends('echeance', 'type')
    def _compute_statut(self):
        today = fields.Date.context_today(self)
        for d in self:
            d.type_txt = dict(DOCS).get(d.type, '')
            if not d.echeance:
                d.statut = 'valide'
            elif d.echeance < today:
                d.statut = 'echu'
            elif d.echeance <= today + timedelta(days=ALERTE_JOURS):
                d.statut = 'proche'
            else:
                d.statut = 'valide'

    @api.model
    def _cron_alertes(self):
        today = fields.Date.context_today(self)
        for d in self.search([('echeance', '!=', False), ('echeance', '<=', today + timedelta(days=ALERTE_JOURS))]):
            v = d.vehicule_id
            resume = _('%s du véhicule %s : échéance le %s') % (d.type_txt, v.name, d.echeance.strftime('%d/%m/%Y'))
            if not v.activity_ids.filtered(lambda a: a.summary == resume):
                v.activity_schedule('mail.mail_activity_data_todo', summary=resume, date_deadline=d.echeance,
                                    user_id=self.env.user.id)
