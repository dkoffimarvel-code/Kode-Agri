from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .common import fmt_dec

SEUIL_CA = 100_000_000   # au-delà, l'autorisation du conseil d'administration est requise (écran 9.3 quater)
ETAPES = [('Demande', 'Département production', 'Émis'), ('Contrôle budgétaire', 'DAF', 'Visé'),
          ('Approbation', 'Direction générale', 'Approuvé'), ('Seuil > 100 M FCFA', "Conseil d'administration", 'Autorisé')]


class KaBab(models.Model):
    """Bon à budgétiser CAPEX : dotation d'investissement, support d'engagement et de suivi (§ 9.2.3)."""
    _name = 'ka.bab'
    _description = 'Bon à budgétiser CAPEX'
    _inherit = ['ka.document', 'mail.thread']
    _order = 'name desc'

    name = fields.Char(string='N° bon', readonly=True, copy=False, default='Nouveau')
    intitule = fields.Char(string='Intitulé', required=True)
    nature = fields.Char(string="Nature d'immobilisation")
    account_id = fields.Many2one('account.account', string='Compte général')
    section_id = fields.Many2one('account.analytic.account', string='Section analytique')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    dotation = fields.Monetary(string='Dotation', required=True)
    periode = fields.Char(string='Période', default=lambda s: '%s' % fields.Date.today().year)
    regle = fields.Selection([('blocage', 'Blocage si engagé > dotation'), ('alerte', 'Alerte seulement')], string='Règles de suivi',
                             default='blocage', required=True)
    budget_id = fields.Many2one('ka.budget', string='Budget validé')
    ligne_ids = fields.Many2many('purchase.order.line', 'ka_bab_pol_rel', 'bab_id', 'pol_id', string='Lignes de commande engagées')
    signature_ids = fields.One2many('ka.bab.signature', 'bab_id', string='Circuit de signature')
    mouvement_ids = fields.One2many('ka.bab.mouvement', 'bab_id', string="Exécution du bon — engagé / réalisé / disponible (M FCFA)")
    engage = fields.Monetary(compute='_compute_exec', string='Engagé')
    realise = fields.Monetary(compute='_compute_exec', string='Réalisé')
    disponible = fields.Monetary(compute='_compute_exec', string='Disponible')
    situation = fields.Char(compute='_compute_exec')
    info = fields.Char(compute='_compute_exec')
    state = fields.Selection([('brouillon', 'Brouillon'), ('emis', 'Émis'), ('vise', 'Visé'), ('approuve', 'Approuvé'),
                              ('autorise', 'Autorisé (CA)')], default='brouillon', string='Statut', tracking=True)
    badge_label = fields.Char(compute='_compute_exec')
    circuit_html = fields.Html(compute='_compute_circuit', sanitize=False, string='Circuit de validation')
    titre = fields.Char(compute='_compute_exec')

    def _ka_subtitle(self):
        self.ensure_one()
        return '%s — %s' % (self.name, self.intitule or '')

    @api.depends('ligne_ids.state', 'ligne_ids.price_subtotal', 'ligne_ids.qty_invoiced', 'ligne_ids.price_unit', 'dotation', 'state',
                 'budget_id', 'budget_id.date_validation')
    def _compute_exec(self):
        etiquettes = {'brouillon': 'Brouillon', 'emis': 'Émis', 'vise': 'Visé', 'approuve': 'Approuvé', 'autorise': 'Autorisé (CA)'}
        for b in self:
            lignes = b.ligne_ids.filtered(lambda l: l.order_id.state in ('purchase', 'done'))
            b.engage = sum(lignes.mapped('price_subtotal'))
            b.realise = sum(l.qty_invoiced * l.price_unit for l in lignes)
            b.disponible = b.dotation - b.engage
            b.situation = 'Situation au %s' % fields.Date.today().strftime('%d/%m/%Y')
            b.badge_label = etiquettes[b.state]
            bud = b.budget_id
            b.titre = 'Bons à budgétiser CAPEX — planification du %s' % (('budget %s' % bud.name) if bud else 'budget validé')
            if bud:
                capex = sum(bud.ligne_ids.filtered(lambda l: (l.account_id.code or '').startswith('2')).mapped('total'))
                bons = self.search([('budget_id', '=', bud.id)])
                capex = capex or sum(bons.mapped('dotation'))
                ca = (' (CA du %s)' % bud.date_validation.strftime('%d/%m/%Y')) if bud.date_validation else ''
                b.info = "Budget CAPEX validé%s : %s MFCFA — planifié sur %d bon(s) à budgétiser ; l'exécution et le suivi portent sur les bons." % (
                    ca, fmt_dec(capex / 1e6), len(bons))
            else:
                b.info = "Bon non rattaché à un budget validé : « Planifier depuis le budget validé » reprend la dotation de la ligne CAPEX ; l'exécution et le suivi portent sur les bons."

    @api.depends('signature_ids.statut', 'signature_ids.date', 'signature_ids.etape', 'signature_ids.signataire')
    def _compute_circuit(self):
        faits = ('Émis', 'Visé', 'Approuvé', 'Autorisé')
        for b in self:
            rows = []
            for sig in b.signature_ids.sorted('id'):
                fait = sig.statut in faits
                quand = ('%s le %s' % (sig.statut, sig.date.strftime('%d/%m/%Y'))) if (fait and sig.date) else (sig.statut or 'À venir')
                rows.append('<div style="display:flex;gap:.6rem;margin:.35rem 0"><span class="o_ka_tag %s" style="padding:0 .45rem">●</span>'
                            '<div><b>%s (%s)</b><div class="o_ka_hint">%s</div></div></div>' % (
                                'o_ka_ok' if fait else 'o_ka_grey', sig.etape or '', sig.signataire or '', quand))
            b.circuit_html = ''.join(rows)

    def action_planifier(self):
        """« Planifier depuis le budget validé » : rattache le bon au budget validé en vigueur de l'année et reprend la dotation
        budgétée sur le compte général (et la section) du bon."""
        for b in self:
            annee = int(b.periode[:4]) if (b.periode or '')[:4].isdigit() else fields.Date.today().year
            bud = b.budget_id if b.budget_id.state == 'valide' else self.env['ka.budget'].search(
                [('annee', '=', annee), ('state', '=', 'valide')], order='revision desc', limit=1)
            if not bud:
                raise UserError(_("Aucun budget validé pour %s : le bon ne peut pas être planifié.") % annee)
            vals = {'budget_id': bud.id}
            lignes = bud.ligne_ids.filtered(lambda l: l.account_id == b.account_id and (not b.section_id or l.section_id == b.section_id))
            if lignes and not b.dotation:
                vals['dotation'] = sum(lignes.mapped('total'))
            b.write(vals)
        return True

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create([dict(v, name=self.env['ir.sequence'].next_by_code('ka.bab')) if v.get('name', 'Nouveau') == 'Nouveau' else v for v in vals_list])
        for b in recs:
            b.signature_ids = [Command.create({'etape': e, 'signataire': s, 'statut': 'À venir'}) for e, s, _st in ETAPES]
        return recs

    def _signer(self, rang, etat):
        self.ensure_one()
        _e, _s, libelle = ETAPES[rang]
        sig = self.signature_ids.sorted('id')[rang]
        sig.write({'date': fields.Date.context_today(self), 'statut': libelle})
        self.state = etat

    def action_soumettre(self):
        for b in self:
            if b.state != 'brouillon':
                raise UserError(_("Ce bon est déjà soumis."))
            b._signer(0, 'emis')

    def action_viser(self):
        for b in self.filtered(lambda b: b.state == 'emis'):
            b._signer(1, 'vise')

    def action_approuver(self):
        for b in self.filtered(lambda b: b.state == 'vise'):
            b._signer(2, 'approuve')
            if b.dotation <= SEUIL_CA:
                b.signature_ids.sorted('id')[3].statut = 'Sans objet'

    def action_autoriser(self):
        for b in self:
            if b.state != 'approuve':
                raise UserError(_("Le bon doit d'abord être approuvé par la direction générale."))
            b._signer(3, 'autorise')

    def action_engager(self):
        self.ensure_one()
        if self.state not in ('approuve', 'autorise') or (self.dotation > SEUIL_CA and self.state != 'autorise'):
            raise UserError(_("L'engagement n'est possible qu'après approbation (autorisation du CA au-delà de 100 M FCFA)."))
        return {'type': 'ir.actions.act_window', 'name': 'Commande d\'achat', 'res_model': 'purchase.order', 'view_mode': 'form',
                'context': {'default_origin': self.name}}

    def action_consulter(self):
        """Reconstitue le tableau d'exécution : dotation initiale, engagements (commandes confirmées), factures."""
        for b in self:
            b.mouvement_ids.unlink()
            lignes = [Command.create({'sequence': 1, 'mouvement': 'Dotation initiale', 'reference': b.name, 'date': b.create_date.date() if b.create_date else False})]
            for l in b.ligne_ids.filtered(lambda l: l.order_id.state in ('purchase', 'done')):
                lignes.append(Command.create({'sequence': 2, 'mouvement': l.name or 'Commande', 'reference': l.order_id.name,
                                              'date': l.order_id.date_order.date() if l.order_id.date_order else False, 'engage': l.price_subtotal}))
                for inv in l.invoice_lines.filtered(lambda i: i.parent_state == 'posted'):
                    lignes.append(Command.create({'sequence': 3, 'mouvement': 'Facture', 'reference': inv.move_id.name, 'date': inv.date, 'realise': inv.price_subtotal}))
            b.mouvement_ids = lignes
            b._recalculer_disponible()
        return True

    def _recalculer_disponible(self):
        self.ensure_one()
        dispo = self.dotation
        for m in self.mouvement_ids.sorted(lambda m: (m.date or fields.Date.today(), m.sequence, m.id)):
            dispo -= m.engage
            m.disponible = dispo if m.sequence != 1 else self.dotation

    @api.constrains('ligne_ids')
    def _check_blocage(self):
        for b in self:
            if b.regle == 'blocage' and b.engage > b.dotation:
                raise UserError(_("Engagé (%s) supérieur à la dotation (%s) : engagement bloqué.") % (fmt_dec(b.engage / 1e6), fmt_dec(b.dotation / 1e6)))


class KaBabSignature(models.Model):
    _name = 'ka.bab.signature'
    _description = 'Étape du circuit de signature'
    _order = 'id'

    bab_id = fields.Many2one('ka.bab', required=True, ondelete='cascade')
    etape = fields.Char(string='Étape')
    signataire = fields.Char(string='Signataire')
    date = fields.Date(string='Date')
    statut = fields.Char(string='Statut')


class KaBabMouvement(models.Model):
    _name = 'ka.bab.mouvement'
    _description = "Mouvement d'exécution d'un bon à budgétiser"
    _order = 'date, sequence, id'

    bab_id = fields.Many2one('ka.bab', required=True, ondelete='cascade')
    sequence = fields.Integer(default=2)
    mouvement = fields.Char(string='Mouvement')
    reference = fields.Char(string='Référence')
    date = fields.Date(string='Date')
    currency_id = fields.Many2one(related='bab_id.currency_id')
    engage = fields.Monetary(string='Engagé')
    realise = fields.Monetary(string='Réalisé')
    disponible = fields.Monetary(string='Disponible')
