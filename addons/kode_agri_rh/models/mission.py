from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import compte, fcfa, journal

COMPTE_AVANCE = '421100'    # personnel, avances et acomptes : avances sur missions, soldé au décompte (RG-7.5)
COMPTE_CHARGE = '618100'    # voyages et déplacements (indemnités forfaitaires de mission)


class KaRhMission(models.Model):
    """Ordre de mission : autorisation préalable, avance, indemnités forfaitaires (per diem) et décompte au retour
    (§ 7.4). Aucune mission n'est clôturée sans régularisation de son avance (RG-7.5)."""
    _name = 'ka.rh.mission'
    _description = 'Ordre de mission'
    _inherit = ['ka.document', 'mail.thread', 'mail.activity.mixin']
    _order = 'date_debut desc, name desc'

    name = fields.Char(string='N° ordre de mission', readonly=True, copy=False, default='Nouveau')
    employe_id = fields.Many2one('ka.rh.employe', string='Missionnaire', required=True)
    fonction = fields.Char(related='employe_id.poste', string='Fonction')
    objet = fields.Char(string='Objet', required=True)
    destination = fields.Char(string='Destination')
    zone = fields.Selection([('interieur', "Intérieur du pays"), ('abidjan', 'Abidjan / port'), ('etranger', 'Étranger')],
                            string='Barème', default='interieur', required=True)
    titre_court = fields.Char(string='Intitulé', help='Ex. Tournée collecte Sud')
    date_debut = fields.Date(string='Début', required=True)
    date_fin = fields.Date(string='Fin', required=True)
    periode_txt = fields.Char(compute='_compute_duree', string='Période')
    duree = fields.Integer(compute='_compute_duree', string='Durée (jours)', store=True)
    duree_txt = fields.Char(compute='_compute_duree', string='Durée')
    moyen_transport = fields.Selection([('vehicule', 'Véhicule de service'), ('commun', 'Transport en commun'),
                                        ('autre', 'Autre')], string='Moyen de transport', default='vehicule')
    vehicule_txt = fields.Char(string='Véhicule de service')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    per_diem = fields.Monetary(string='Per diem / jour', compute='_compute_bareme', store=True, readonly=False)
    hebergement = fields.Monetary(string='Hébergement / nuit', compute='_compute_bareme', store=True, readonly=False)
    avance_demandee = fields.Monetary(string='Avance demandée')
    avance_txt = fields.Char(compute='_compute_decompte', string='Avance')
    analytic_id = fields.Many2one('account.analytic.account', string='Activité analytique')
    avance_versee = fields.Monetary(string='Avance versée', readonly=True, copy=False)
    note_ids = fields.Many2many('ka.frais.note', string='Notes de frais (frais réels)')
    indemnites = fields.Monetary(compute='_compute_decompte', string='Indemnités dues', store=True)
    frais_reels = fields.Monetary(compute='_compute_decompte', string='Frais réels', store=True)
    regularisation = fields.Monetary(compute='_compute_decompte', string='Régularisation', store=True)
    solde_avance = fields.Monetary(compute='_compute_decompte', string="Solde du compte d'avance", store=True,
                                   help="Indemnités dues − avance versée ; les frais réels sont remboursés par leur note "
                                        "de frais (module 6)")
    regul_txt = fields.Char(compute='_compute_decompte', string='Régularisation')
    decompte_html = fields.Html(compute='_compute_decompte', sanitize=False)
    retenue_paie = fields.Boolean(string='Trop-perçu retenu sur la paie', default=True)
    bulletin_id = fields.Many2one('ka.rh.bulletin', string='Bulletin de retenue', readonly=True, copy=False)
    move_ids = fields.Many2many('account.move', string='Écritures', readonly=True, copy=False)
    titre = fields.Char(compute='_compute_duree')
    state = fields.Selection([('brouillon', 'Brouillon'), ('a_approuver', 'À approuver'), ('en_cours', 'En cours'),
                              ('a_regulariser', 'À régulariser'), ('cloturee', 'Clôturée'), ('refusee', 'Refusée')],
                             default='brouillon', string='Statut', tracking=True)

    @api.depends('name', 'titre_court', 'objet')
    def _compute_display_name(self):
        for m in self:
            m.display_name = '%s — %s' % (m.name, m.titre_court or m.objet or '')

    def _ka_subtitle(self):
        self.ensure_one()
        return ' · '.join(x for x in (self.fonction, self.titre_court or self.objet) if x)

    @api.depends('date_debut', 'date_fin')
    def _compute_duree(self):
        for m in self:
            m.duree = (m.date_fin - m.date_debut).days + 1 if m.date_debut and m.date_fin and m.date_fin >= m.date_debut else 0
            m.duree_txt = '%d j' % m.duree
            m.titre = _('Ordre de mission %s') % (m.name or '')
            if m.date_debut and m.date_fin:
                fmt = '%d' if m.date_debut.month == m.date_fin.month and m.date_debut.year == m.date_fin.year else '%d/%m'
                m.periode_txt = '%s–%s' % (m.date_debut.strftime(fmt), m.date_fin.strftime('%d/%m/%Y'))
            else:
                m.periode_txt = ''

    @api.depends('employe_id.categorie_id', 'zone')
    def _compute_bareme(self):
        for m in self:
            b = self.env['ka.rh.bareme.mission'].taux(m.employe_id.categorie_id, m.zone)
            m.per_diem, m.hebergement = b.per_diem, b.hebergement

    @api.depends('per_diem', 'duree', 'note_ids.total', 'avance_versee', 'avance_demandee')
    def _compute_decompte(self):
        for m in self:
            m.indemnites = m.per_diem * m.duree
            m.frais_reels = sum(m.note_ids.mapped('total'))
            m.regularisation = m.indemnites + m.frais_reels - m.avance_versee
            m.solde_avance = m.indemnites - m.avance_versee
            m.avance_txt = fcfa(m.avance_versee or m.avance_demandee)
            r = m.regularisation
            m.regul_txt = ('%s%s FCFA (%s)' % ('+' if r > 0 else '', fcfa(r), _('complément à verser') if r > 0 else
                                               _('trop-perçu à récupérer'))) if r else _('Soldée')
            notes = ', '.join(m.note_ids.mapped('name')) or '—'
            rows = [(_('Per diem'), '%s × %d jours' % (fcfa(m.per_diem), m.duree), fcfa(m.indemnites)),
                    (_('Frais réels (note de frais %s)') % notes, _('Justificatifs'), fcfa(m.frais_reels)),
                    (_('Avance versée'), '', fcfa(-m.avance_versee) if m.avance_versee else '0')]
            m.decompte_html = (
                '<table class="o_ka_tbl"><thead><tr><th>Élément</th><th>Base</th><th class="o_ka_num">Montant</th></tr>'
                '</thead><tbody>%s</tbody><tfoot><tr><td>Régularisation</td><td></td><td class="o_ka_num">%s</td></tr>'
                '</tfoot></table>' % (''.join('<tr><td>%s</td><td>%s</td><td class="o_ka_num">%s</td></tr>' % r_ for r_ in rows),
                                      m.regul_txt))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.rh.mission')
        return super().create(vals_list)

    # ---- cycle (§ 7.4.3) ------------------------------------------------------------------------------------------
    def action_soumettre(self):
        for m in self.filtered(lambda x: x.state == 'brouillon'):
            m.state = 'a_approuver'
            m.activity_schedule('mail.mail_activity_data_todo', summary=_('Ordre de mission %s à approuver') % m.name,
                                user_id=self.env.user.id)

    def action_approuver(self):
        for m in self.filtered(lambda x: x.state == 'a_approuver'):
            m.state = 'en_cours'
            m.activity_ids.action_feedback(feedback=_('Approuvé'))

    def action_refuser(self):
        self.filtered(lambda x: x.state == 'a_approuver').write({'state': 'refusee'})

    def _ecriture(self, lib, lignes):
        move = self.env['account.move'].create({'move_type': 'entry', 'journal_id': journal(self.env, 'OD').id,
                                                'date': fields.Date.context_today(self), 'ref': lib,
                                                'line_ids': [Command.create(l) for l in lignes]})
        move.action_post()
        self.move_ids = [Command.link(move.id)]
        return move

    def _tresorerie(self):
        j = self.env['account.journal'].search([('type', '=', 'cash')], limit=1) \
            or self.env['account.journal'].search([('type', '=', 'bank')], limit=1)
        if not j.default_account_id:
            raise UserError(_('Aucun journal de caisse ou de banque avec compte par défaut.'))
        return j.default_account_id

    def action_verser_avance(self):
        """Décaissement de l'avance au collaborateur, portée au compte de tiers « avances sur missions »."""
        for m in self:
            if m.state != 'en_cours':
                raise UserError(_("L'avance n'est versée qu'après approbation de l'ordre de mission."))
            if m.avance_versee or not m.avance_demandee:
                raise UserError(_("Aucune avance à verser."))
            p, lib = m.employe_id.partner_id, _('Avance mission %s') % m.name
            m._ecriture(lib, [{'account_id': compte(self.env, COMPTE_AVANCE).id, 'name': lib, 'debit': m.avance_demandee,
                               'partner_id': p.id},
                              {'account_id': m._tresorerie().id, 'name': lib, 'credit': m.avance_demandee}])
            m.avance_versee = m.avance_demandee

    def action_decompter(self):
        """Au retour : indemnités dues (per diem × jours) et frais réels rattachés (notes de frais, module 6)."""
        for m in self:
            if m.state != 'en_cours':
                raise UserError(_('Seule une mission en cours peut être décomptée.'))
            p, lib = m.employe_id.partner_id, _('Indemnités mission %s') % m.name
            if m.indemnites:
                ana = {str(m.analytic_id.id): 100} if m.analytic_id else False
                m._ecriture(lib, [{'account_id': compte(self.env, COMPTE_CHARGE).id, 'name': lib, 'debit': m.indemnites,
                                   'analytic_distribution': ana},
                                  {'account_id': compte(self.env, COMPTE_AVANCE).id, 'name': lib, 'credit': m.indemnites,
                                   'partner_id': p.id}])
            m.state = 'a_regulariser'

    def action_regulariser(self):
        """RG-7.5 : complément versé au collaborateur, ou trop-perçu récupéré (retenue sur la paie ou remboursement)."""
        for m in self:
            if m.state != 'a_regulariser':
                raise UserError(_('Décomptez la mission avant de la régulariser.'))
            solde_avance = m.solde_avance   # solde du compte d'avance après le décompte
            p, lib = m.employe_id.partner_id, _('Régularisation mission %s') % m.name
            if solde_avance > 0:   # complément des indemnités ; les frais réels sont remboursés par leur note de frais
                m._ecriture(lib, [{'account_id': compte(self.env, COMPTE_AVANCE).id, 'name': lib, 'debit': solde_avance,
                                   'partner_id': p.id},
                                  {'account_id': m._tresorerie().id, 'name': lib, 'credit': solde_avance}])
            elif solde_avance < 0 and m.retenue_paie:   # soldé par l'écriture de paie (crédit du compte d'avance)
                if not (m.bulletin_id and m.bulletin_id.state in ('confirme', 'paye')):
                    raise UserError(_("Trop-perçu de %s FCFA : il sera soldé par la retenue sur le prochain bulletin "
                                      "confirmé (RG-7.5).") % fcfa(-solde_avance))
            elif solde_avance < 0:   # remboursement par le collaborateur
                m._ecriture(lib, [{'account_id': m._tresorerie().id, 'name': lib, 'debit': -solde_avance},
                                  {'account_id': compte(self.env, COMPTE_AVANCE).id, 'name': lib, 'credit': -solde_avance,
                                   'partner_id': p.id}])
            m.state = 'cloturee'

    def action_voir_ecritures(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Écritures'), 'res_model': 'account.move',
                'view_mode': 'list,form', 'domain': [('id', 'in', self.move_ids.ids)]}
