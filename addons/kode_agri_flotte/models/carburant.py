import base64
import csv
import io

from odoo import Command, _, api, fields, models
from odoo.addons.kode_agri_gestion.models.common import section
from odoo.addons.kode_agri_maintenance.models.equipement import nb
from odoo.addons.kode_agri_rh.models.common import compte, journal

from .achat import SECTION_USAGE
from .vehicule import dec

TOLERANCE_DERIVE = 0.05   # au-delà de +5 % de la consommation moyenne : dérive (surconsommation, fuite, usage non conforme)
COMPTE_CARBURANT = '602200'
COMPTE_FNP = '4081'        # fournisseurs — factures non parvenues (relevé de cartes carburant)


class KaFloPlein(models.Model):
    """Plein ou dotation de carburant (§ 11.3) : rapproché du kilométrage parcouru pour la consommation moyenne et la
    détection des dérives ; coût imputé par véhicule et par zone de collecte ; rapprochement avec les relevés du
    fournisseur (cartes ou bons carburant)."""
    _name = 'ka.flo.plein'
    _description = 'Plein de carburant'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'date desc, km desc'

    name = fields.Char(string='N° plein', readonly=True, copy=False, default='Nouveau')
    vehicule_id = fields.Many2one('ka.flo.vehicule', string='Véhicule', required=True)
    date = fields.Date(string='Date du plein', required=True, default=fields.Date.context_today)
    quantite = fields.Float(string='Quantité (L)', required=True, digits=(10, 1))
    quantite_txt = fields.Char(compute='_compute_conso', string='Quantité')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    cout = fields.Monetary(string='Coût', required=True)
    km = fields.Float(string='Km au plein', required=True, digits=(12, 0))
    km_parcourus = fields.Float(compute='_compute_conso', string='Km depuis dernier plein', store=True, digits=(12, 0))
    conso = fields.Float(compute='_compute_conso', string='Conso calculée (L/100 km)', store=True, digits=(6, 2))
    conso_txt = fields.Char(compute='_compute_conso', string='Conso calculée')
    conso_liste = fields.Char(compute='_compute_conso', string='Conso (L/100)')
    conso_moy_txt = fields.Char(compute='_compute_conso', string='Conso moy.')
    ecart_txt = fields.Char(compute='_compute_conso', string='Écart')
    derive = fields.Boolean(compute='_compute_conso', string='Dérive', store=True)
    zone_id = fields.Many2one('account.analytic.account', string='Zone de collecte (analytique)',
                              compute='_compute_zone', store=True, readonly=False)
    mode = fields.Selection([('carte', 'Carte carburant'), ('bon', 'Bon carburant'), ('cuve', 'Cuve interne')],
                            string='Mode', default='carte', required=True)
    support = fields.Char(string='N° de carte ou de bon', help='Ex. CARB-014, BC-7740')
    support_txt = fields.Char(compute='_compute_conso', string='Bon / carte')
    historique_ids = fields.Many2many('ka.flo.plein', compute='_compute_historique', string='Historique des pleins')
    move_id = fields.Many2one('account.move', string='Écriture', readonly=True, copy=False)
    titre = fields.Char(compute='_compute_conso')
    state = fields.Selection([('saisi', 'Saisi'), ('rapproche', 'Rapproché')], default='saisi', string='Statut', tracking=True)

    def _ka_subtitle(self):
        self.ensure_one()
        return _('%s · suivi consommation et dérives') % (self.vehicule_id.name or '')

    @api.depends('name', 'vehicule_id')
    def _compute_display_name(self):
        for p in self:
            p.display_name = '%s — %s' % (p.name, p.vehicule_id.name or '')

    @api.depends('vehicule_id')
    def _compute_zone(self):
        for p in self:
            p.zone_id = p.vehicule_id.zone_id

    def _precedent(self):
        self.ensure_one()
        return self.search([('vehicule_id', '=', self.vehicule_id.id), ('km', '<', self.km), ('id', '!=', self._origin.id)],
                           order='km desc', limit=1)

    @api.depends('km', 'quantite', 'vehicule_id', 'mode', 'support', 'name')
    def _compute_conso(self):
        for p in self:
            prec = p._precedent() if p.vehicule_id and p.km else self.browse()
            p.km_parcourus = p.km - prec.km if prec else 0.0
            p.conso = 100.0 * p.quantite / p.km_parcourus if p.km_parcourus else 0.0
            moy = p.vehicule_id.conso_moyenne
            p.derive = bool(moy and p.conso > moy * (1 + TOLERANCE_DERIVE))
            p.titre = _('Plein carburant %s') % (p.name or '')
            p.quantite_txt = '%s L' % dec(p.quantite, 0)
            p.conso_txt = '%s L/100 km' % dec(p.conso)
            p.conso_liste = dec(p.conso) + (_(' (dérive)') if p.derive else '')
            p.conso_moy_txt = '%s L/100' % dec(moy)
            ecart_l = (p.conso - moy) * p.km_parcourus / 100.0 if moy and p.km_parcourus else 0.0
            p.ecart_txt = '%s%s L' % ('+' if ecart_l > 0 else '', dec(ecart_l))
            p.support_txt = '%s %s' % ({'carte': _('Carte'), 'bon': _('Bon'), 'cuve': _('Cuve')}[p.mode or 'carte'], p.support or '')

    def _compute_historique(self):
        for p in self:
            p.historique_ids = self.search([('vehicule_id', '=', p.vehicule_id.id)], order='date desc, km desc', limit=10) \
                if p.vehicule_id else self.browse()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.flo.plein')
        recs = super().create(vals_list)
        for p in recs:
            p.vehicule_id.maj_compteur(p.km, p.name, p.date)
            p._comptabiliser()
            if p.derive:
                p.vehicule_id.message_post(body=_('Dérive de consommation : %s (moyenne %s), plein %s.') % (
                    p.conso_txt, p.conso_moy_txt, p.name))
        return recs

    def _comptabiliser(self):
        """Charge de carburant imputée à l'activité de la tournée (module 9), au véhicule et à la zone de collecte ;
        contrepartie au compte des factures non parvenues, soldé par la facture du relevé fournisseur."""
        for p in self.filtered(lambda x: not x.move_id and x.cout):
            comptes = [section(self.env, SECTION_USAGE.get(p.vehicule_id.categorie, 'USINAGE')), p.vehicule_id.analytic_id, p.zone_id]
            ana = ','.join(str(a.id) for a in comptes if a)
            lib = _('Carburant %s — %s') % (p.vehicule_id.name, p.name)
            move = self.env['account.move'].create({
                'move_type': 'entry', 'journal_id': journal(self.env, 'OD').id, 'date': p.date, 'ref': lib,
                'line_ids': [Command.create({'account_id': compte(self.env, COMPTE_CARBURANT).id, 'name': lib, 'debit': p.cout,
                                             'analytic_distribution': {ana: 100} if ana else False}),
                             Command.create({'account_id': compte(self.env, COMPTE_FNP).id, 'name': lib, 'credit': p.cout})]})
            move.action_post()
            p.move_id = move

    def action_nouveau_plein(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.flo.plein', 'view_mode': 'form',
                'context': {'default_vehicule_id': self[:1].vehicule_id.id, 'default_mode': self[:1].mode,
                            'default_support': self[:1].support}}

    def action_voir_piece(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': self.move_id.id, 'view_mode': 'form'}

    def action_open_vehicule(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ka.flo.vehicule', 'res_id': self.vehicule_id.id, 'view_mode': 'form'}


class KaFloReleveImport(models.TransientModel):
    """Import du relevé du fournisseur de cartes carburant : chaque ligne est rapprochée d'un plein saisi (même carte,
    même date, quantité à 1 % près) ; les lignes sans plein sont signalées."""
    _name = 'ka.flo.releve.import'
    _description = 'Import du relevé de cartes carburant'

    fichier = fields.Binary(string='Relevé (CSV : carte;date;quantite;montant)', required=True)
    nom = fields.Char(string='Nom du fichier')
    rapport = fields.Text(string='Rapport', readonly=True)

    def action_importer(self):
        self.ensure_one()
        texte = base64.b64decode(self.fichier).decode('utf-8-sig')
        lignes = list(csv.reader(io.StringIO(texte), delimiter=';'))
        Plein, ok, ko = self.env['ka.flo.plein'], 0, []
        for i, l in enumerate(lignes):
            if not l or l[0].strip().lower() in ('carte', 'card'):
                continue
            try:
                carte, jour, qte, montant = l[0].strip(), fields.Date.to_date(l[1].strip()), float(l[2].replace(',', '.')), float(l[3].replace(',', '.'))
            except (ValueError, IndexError):
                ko.append(_('ligne %d illisible') % (i + 1))
                continue
            p = Plein.search([('support', '=', carte), ('date', '=', jour), ('state', '=', 'saisi')]).filtered(
                lambda x: abs(x.quantite - qte) <= 0.01 * qte)[:1]
            if p:
                p.state = 'rapproche'
                if abs(p.cout - montant) > 1:
                    p.message_post(body=_('Écart de montant avec le relevé : %s FCFA au relevé, %s FCFA saisis.') % (nb(montant), nb(p.cout)))
                ok += 1
            else:
                ko.append(_('%s du %s (%s L) : aucun plein saisi') % (carte, jour, qte))
        self.rapport = _('%d plein(s) rapproché(s).') % ok + ('\n' + '\n'.join(ko) if ko else '')
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'target': 'new'}
