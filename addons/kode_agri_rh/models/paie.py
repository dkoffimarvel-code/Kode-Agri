from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import compte, fcfa, journal, mois_txt


class KaRhBulletin(models.Model):
    """Bulletin de paie (§ 7.3) : cascade salaire de base → primes et indemnités → brut → cotisations CNPS →
    net imposable → ITS (barème progressif, réduction pour charges de famille) → autres retenues → net à payer.
    Les valeurs (taux, plafonds, barèmes) sont lues à la date de la période : un bulletin confirmé n'est jamais recalculé
    (RG-7.4). La confirmation génère les écritures de paie ventilées sur le compte analytique de l'affectation."""
    _name = 'ka.rh.bulletin'
    _description = 'Bulletin de paie'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'periode desc, name desc'

    name = fields.Char(string='N° bulletin', readonly=True, copy=False, default='Nouveau')
    employe_id = fields.Many2one('ka.rh.employe', string='Employé', required=True)
    affectation_id = fields.Many2one(related='employe_id.affectation_id', store=True, string='Affectation')
    analytic_id = fields.Many2one('account.analytic.account', string='Compte analytique',
                                  compute='_compute_analytic', store=True, readonly=False)
    periode = fields.Date(string='Période', required=True,
                          default=lambda s: fields.Date.context_today(s).replace(day=1))
    periode_txt = fields.Char(compute='_compute_periode', string='Période')
    ligne_ids = fields.One2many('ka.rh.bulletin.ligne', 'bulletin_id', string='Lignes de paie')
    ligne_affichee_ids = fields.One2many('ka.rh.bulletin.ligne', 'bulletin_id', string='Lignes du bulletin',
                                         domain=[('affiche', '=', True), ('nature', '!=', 'total')])
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    brut = fields.Monetary(string='Salaire brut', readonly=True)
    cotisations = fields.Monetary(string='Cotisations salariales', readonly=True)
    imposable = fields.Monetary(string='Net imposable', readonly=True)
    its = fields.Monetary(string='ITS', readonly=True)
    autres_retenues = fields.Monetary(string='Autres retenues', readonly=True)
    net = fields.Monetary(string='Net à payer', readonly=True)
    net_txt = fields.Char(compute='_compute_net_txt', string='Net à payer')
    charges_patronales = fields.Monetary(string='Charges patronales', readonly=True)
    heures_sup = fields.Float(string='Heures supplémentaires', readonly=True)
    move_id = fields.Many2one('account.move', string='Écriture de paie', readonly=True, copy=False)
    mission_ids = fields.One2many('ka.rh.mission', 'bulletin_id', string='Missions régularisées', readonly=True)
    titre = fields.Char(compute='_compute_periode')
    valid_txt = fields.Char(compute='_compute_periode')
    state = fields.Selection([('brouillon', 'Brouillon'), ('calcule', 'Calculé'), ('confirme', 'Confirmé'),
                              ('paye', 'Payé')], default='brouillon', string='Statut', tracking=True)

    @api.depends('name', 'employe_id')
    def _compute_display_name(self):
        for b in self:
            b.display_name = '%s — %s' % (b.name, b.employe_id.matricule or '')

    def _ka_subtitle(self):
        self.ensure_one()
        return ' · '.join(x for x in (self.employe_id.poste, mois_txt(self.periode)) if x)

    @api.depends('employe_id')
    def _compute_analytic(self):
        for b in self:
            b.analytic_id = b.employe_id.analytic_id or b.employe_id.affectation_id.analytic_id

    @api.depends('periode', 'name', 'analytic_id')
    def _compute_periode(self):
        for b in self:
            b.periode_txt = mois_txt(b.periode)
            b.titre = _('Bulletin %s') % (b.name or '')
            b.valid_txt = _('Confirmation → génération des écritures de paie ; charges de personnel imputées '
                            'analytiquement (%s).') % (b.analytic_id.name or b.affectation_id.name or _('affectation'))

    @api.depends('net', 'currency_id')
    def _compute_net_txt(self):
        for b in self:
            b.net_txt = '%s FCFA' % fcfa(b.net)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('ka.rh.bulletin')
            if vals.get('periode'):
                vals['periode'] = fields.Date.to_date(vals['periode']).replace(day=1)
        return super().create(vals_list)

    # ---- calcul -------------------------------------------------------------------------------------------------
    def action_calculer(self):
        Rub = self.env['ka.rh.rubrique']
        for b in self:
            if b.state not in ('brouillon', 'calcule'):
                raise UserError(_('Un bulletin confirmé ne peut plus être recalculé (RG-7.4).'))
            e, d = b.employe_id, b.periode
            fin = d + relativedelta(months=1, days=-1)
            lignes, seq = [], [0]

            def ligne(code, montant, base=0.0, taux=0.0, base_txt='', taux_txt='', libelle=None):
                r = Rub.par_code(code)
                seq[0] += 1
                lignes.append(Command.create({'rubrique_id': r.id, 'libelle': libelle or r.name, 'sequence': r.sequence * 100 + seq[0],
                                              'base': base, 'taux': taux, 'base_txt': base_txt, 'taux_txt': taux_txt,
                                              'montant': round(montant), 'affiche': r.affiche, 'nature': r.nature}))
                return round(montant)

            def v(code):
                return Rub.par_code(code).valeur_a(d)
            # 1. salaire de base, heures supplémentaires, primes et indemnités
            gains = soumis_its = 0.0
            for el in e.element_ids.sorted('sequence'):
                est_base = el.rubrique_id.categorie == 'base'
                m = ligne(el.rubrique_id.code, el.montant, base=el.montant if est_base else 0.0,
                          base_txt=fcfa(el.montant) if est_base else '')
                gains += m
                soumis_its += m if el.rubrique_id.soumis_its else 0.0
            feuilles = self.env['ka.rh.feuille'].search([('employe_id', '=', e.id), ('state', 'in', ('validee', 'transmise')),
                                                         ('date_debut', '>=', d - relativedelta(days=6)), ('date_debut', '<=', fin)])
            hs = sum(feuilles.ligne_ids.filtered(lambda l: d <= l.date <= fin).mapped('heures_sup'))
            if hs:
                maj = v('HS').taux or 1.25
                m = ligne('HS', hs * e.taux_horaire * maj, base=hs, taux=maj, base_txt='%g h' % round(hs, 2),
                          taux_txt=('%g' % maj).replace('.', ','))
                gains += m
                soumis_its += m
            # absences non rémunérées (absence injustifiée, permission au-delà du plafond, congé sans solde)
            nr = sum(self.env['ka.rh.demande'].search([('employe_id', '=', e.id), ('state', '=', 'approuvee'),
                                                       ('date_debut', '>=', d), ('date_debut', '<=', fin)]).mapped('jours_non_remuneres'))
            if nr:
                m = ligne('ABS', -e.salaire_base / 26.0 * nr, base=nr, base_txt='%g j' % nr)
                gains += m
                soumis_its += m
            brut = gains
            # 2. cotisations sociales salariales (CNPS retraite, plafonnée)
            ret = v('CNPS_RET_SAL')
            assiette = min(brut, ret.plafond) if ret.plafond else brut
            cot = ligne('CNPS_RET_SAL', -assiette * ret.taux, base=assiette, taux=-ret.taux, base_txt=fcfa(assiette),
                        taux_txt=('-%g%%' % (ret.taux * 100)).replace('.', ','), libelle=_('Cotisations sociales'))
            # 3. net imposable et ITS (barème progressif − réduction pour charges de famille)
            imposable = soumis_its + cot
            its_brut = self.env['ka.rh.its.tranche'].calculer(imposable, d)
            ricf = self.env['ka.rh.ricf'].reduction(e.parts, d)
            its = max(its_brut - ricf, 0.0)
            its = -ligne('ITS', -its, base=imposable, base_txt=fcfa(imposable)) if its else 0.0
            # 4. autres retenues : trop-perçu de mission non régularisé (RG-7.5)
            missions = self.env['ka.rh.mission'].search([('employe_id', '=', e.id), ('state', '=', 'a_regulariser'),
                                                         ('solde_avance', '<', 0), ('retenue_paie', '=', True),
                                                         ('bulletin_id', '=', False)])
            autres = 0.0
            for mi in missions:
                autres -= ligne('RET_MISSION', mi.solde_avance, libelle=_('Trop-perçu mission %s') % mi.name)
            net = brut + cot - its - autres
            ligne('NET', net, libelle=_('Net à payer'))
            # 5. charges patronales (non imprimées) : CNPS et contributions FDFP
            pat = 0.0
            for code in ('CNPS_PF', 'CNPS_AT', 'CNPS_RET_PAT', 'FDFP_TA', 'FDFP_FPC'):
                val = v(code)
                a = min(brut, val.plafond) if val.plafond else brut
                pat += ligne(code, a * val.taux, base=a, taux=val.taux)
            b.ligne_ids.unlink()
            b.write({'ligne_ids': lignes, 'brut': brut, 'cotisations': -cot, 'imposable': imposable, 'its': its,
                     'autres_retenues': autres, 'net': net, 'charges_patronales': pat, 'heures_sup': hs,
                     'state': 'calcule'})
            missions.write({'bulletin_id': b.id})

    def action_confirmer(self):
        for b in self:
            if b.state == 'brouillon':
                b.action_calculer()
            if b.state != 'calcule':
                continue
            b.state = 'confirme'
            b.action_comptabiliser()

    def action_comptabiliser(self):
        """Écritures de paie : charges de personnel imputées analytiquement (atelier, ligne, zone de collecte)."""
        for b in self:
            if b.move_id:
                continue
            if b.state not in ('confirme', 'paye'):
                raise UserError(_('Confirmez le bulletin avant de le comptabiliser.'))
            ana = {str(b.analytic_id.id): 100} if b.analytic_id else False
            p = b.employe_id.partner_id
            lib = '%s %s' % (b.name, b.employe_id.matricule)
            cot_pat = sum(b.ligne_ids.filtered(lambda l: l.rubrique_id.code.startswith('CNPS_')
                                               and l.nature == 'patronal').mapped('montant'))
            fdfp = b.charges_patronales - cot_pat
            mouvements = [  # compte, débit, crédit, analytique, tiers
                ('661100', b.brut, 0.0, ana, False), ('664100', b.charges_patronales, 0.0, ana, False),
                ('431100', 0.0, b.cotisations + cot_pat, False, False), ('447200', 0.0, b.its, False, False),
                ('447300', 0.0, fdfp, False, False), ('425100', 0.0, b.autres_retenues, False, p.id),
                ('422100', 0.0, b.net, False, p.id)]
            lignes = [Command.create({'account_id': compte(self.env, c).id, 'name': lib, 'debit': dt, 'credit': ct,
                                      'analytic_distribution': a, 'partner_id': t})
                      for c, dt, ct, a, t in mouvements if dt or ct]
            move = self.env['account.move'].create({'move_type': 'entry', 'journal_id': journal(self.env, 'PAIE').id,
                                                    'date': b.periode + relativedelta(months=1, days=-1),
                                                    'ref': lib, 'line_ids': lignes})
            move.action_post()
            b.move_id = move

    def action_payer(self):
        self.filtered(lambda b: b.state == 'confirme').write({'state': 'paye'})

    def action_brouillon(self):
        for b in self:
            if b.state != 'calcule':
                raise UserError(_('Seul un bulletin calculé et non confirmé repasse en brouillon.'))
            b.mission_ids.write({'bulletin_id': False})
            b.write({'state': 'brouillon'})

    def action_voir_piece(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_("Aucune écriture n'a encore été générée."))
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': self.move_id.id, 'view_mode': 'form'}

    @api.model
    def generer_lot(self, periode=None):
        """Bulletins par lot : un bulletin calculé par salarié actif pour la période (mois en cours par défaut)."""
        periode = fields.Date.to_date(periode) if periode else fields.Date.context_today(self).replace(day=1)
        crees = self.browse()
        for e in self.env['ka.rh.employe'].search([('state', '=', 'actif')]):
            if not self.search_count([('employe_id', '=', e.id), ('periode', '=', periode.replace(day=1))]):
                crees |= self.create({'employe_id': e.id, 'periode': periode})
        crees.action_calculer()
        return {'type': 'ir.actions.act_window', 'name': _('Bulletins %s') % mois_txt(periode), 'res_model': 'ka.rh.bulletin',
                'view_mode': 'list,form', 'domain': [('periode', '=', periode.replace(day=1))]}


class KaRhBulletinLigne(models.Model):
    """Ligne de bulletin : rubrique appliquée, base, taux et montant (journal des rubriques, livre de paie)."""
    _name = 'ka.rh.bulletin.ligne'
    _description = 'Ligne de bulletin de paie'
    _order = 'bulletin_id, sequence, id'

    bulletin_id = fields.Many2one('ka.rh.bulletin', required=True, ondelete='cascade')
    employe_id = fields.Many2one(related='bulletin_id.employe_id', store=True, string='Employé')
    periode = fields.Date(related='bulletin_id.periode', store=True, string='Période')
    affectation_id = fields.Many2one(related='bulletin_id.affectation_id', store=True, string='Affectation')
    rubrique_id = fields.Many2one('ka.rh.rubrique', string='Code', required=True)
    categorie = fields.Selection(related='rubrique_id.categorie', store=True, string='Catégorie')
    nature = fields.Selection([('gain', 'Gain'), ('retenue', 'Retenue'), ('patronal', 'Charge patronale'),
                               ('total', 'Total')], string='Nature')
    libelle = fields.Char(string='Rubrique')
    sequence = fields.Integer()
    base = fields.Float(string='Base (valeur)', digits=(14, 2))
    taux = fields.Float(string='Taux (valeur)', digits=(8, 4))
    base_txt = fields.Char(string='Base')
    taux_txt = fields.Char(string='Taux')
    currency_id = fields.Many2one(related='bulletin_id.currency_id')
    montant = fields.Monetary(string='Montant')
    affiche = fields.Boolean(string='Imprimée')
