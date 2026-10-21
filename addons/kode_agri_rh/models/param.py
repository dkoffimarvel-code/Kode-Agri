from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class KaRhAffectation(models.Model):
    """Affectation du personnel : atelier / ligne, zone de collecte ou service administratif (§ 7.1)."""
    _name = 'ka.rh.affectation'
    _description = 'Affectation du personnel'
    _order = 'type, name'

    name = fields.Char(string='Affectation', required=True, help='Ex. Atelier / Ligne 2')
    libelle = fields.Char(string='Libellé long', help='Ex. Atelier production')
    type = fields.Selection([('atelier', 'Atelier'), ('collecte', 'Zone de collecte'),
                             ('administration', 'Administration')], string='Type', required=True, default='atelier')
    analytic_id = fields.Many2one('account.analytic.account', string='Compte analytique')
    responsable = fields.Char(string='Responsable hiérarchique', help='Valideur des congés et des pointages')


class KaRhCategorie(models.Model):
    """Catégorie professionnelle : durée maximale de la période d'essai (RG-7.7) et structure de paie."""
    _name = 'ka.rh.categorie'
    _description = 'Catégorie professionnelle'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    name = fields.Char(string='Catégorie', required=True)
    essai_mois = fields.Integer(string="Période d'essai maximale (mois)", required=True,
                                help="Décret du 16 octobre 2024 (art. 14.5 du Code du travail) — paramètre modifiable")
    structure = fields.Selection([('horaire', 'Opérateur rémunéré à l\'heure'), ('mensuel', 'Salaire mensuel fixe')],
                                 string='Structure de paie', default='mensuel', required=True)


class KaRhRubrique(models.Model):
    """Rubrique de paie (§ 7.3.1-7.3.2) : gain ou retenue, mode de calcul, séquence et assujettissements.
    Les taux, montants et plafonds sont historisés avec leur date d'effet (RG-7.4)."""
    _name = 'ka.rh.rubrique'
    _description = 'Rubrique de paie'
    _order = 'sequence, id'

    code = fields.Char(string='Code', required=True, help='Ex. PRIM_TRANSPORT')
    name = fields.Char(string='Libellé', required=True)
    nature = fields.Selection([('gain', 'Gain'), ('retenue', 'Retenue'), ('patronal', 'Charge patronale'),
                               ('total', 'Total')], string='Nature', required=True, default='gain')
    categorie = fields.Selection([('base', 'Salaire de base'), ('indemnite', 'Primes et indemnités'),
                                  ('cot_sal', 'Cotisations salariales'), ('cot_pat', 'Cotisations patronales'),
                                  ('impot', 'Impôt'), ('autre', 'Autres retenues'), ('net', 'Net')],
                                 string='Catégorie', required=True, default='indemnite')
    mode = fields.Selection([('fixe', 'Montant fixe'), ('pct', "Pourcentage d'une base"),
                             ('formule', 'Formule conditionnelle')], string='Mode de calcul', default='fixe', required=True)
    base = fields.Selection([('base', 'Salaire de base'), ('brut', 'Salaire brut'), ('heures', 'Heures pointées'),
                             ('imposable', 'Net imposable')], string='Base de calcul')
    sequence = fields.Integer(string='Séquence', default=100)
    soumis_cnps = fields.Boolean(string='Soumis CNPS', default=True)
    soumis_its = fields.Boolean(string='Soumis ITS', default=True)
    affiche = fields.Boolean(string='Affichée sur le bulletin', default=True)
    compte_code = fields.Char(string='Compte', help='Compte de charge ou de tiers de la rubrique')
    valeur_ids = fields.One2many('ka.rh.rubrique.valeur', 'rubrique_id', string='Valeurs historisées')
    taux = fields.Float(compute='_compute_courant', string='Taux en vigueur', digits=(8, 4))
    plafond = fields.Float(compute='_compute_courant', string='Plafond en vigueur', digits=(14, 0))

    @api.constrains('code')
    def _check_code(self):
        for r in self:
            if self.search_count([('code', '=', r.code)]) > 1:
                raise ValidationError(_('Le code de rubrique %s existe déjà.') % r.code)

    @api.depends('valeur_ids.date_effet', 'valeur_ids.taux', 'valeur_ids.plafond')
    def _compute_courant(self):
        today = fields.Date.context_today(self)
        for r in self:
            v = r.valeur_a(today)
            r.taux, r.plafond = v.taux, v.plafond

    def valeur_a(self, date):
        """Valeur en vigueur à une date : la dernière dont la date d'effet est antérieure ou égale (RG-7.4)."""
        self.ensure_one()
        return self.valeur_ids.filtered(lambda v: v.date_effet <= date).sorted('date_effet')[-1:] \
            or self.env['ka.rh.rubrique.valeur']

    @api.model
    def par_code(self, code):
        r = self.search([('code', '=', code)], limit=1)
        if not r:
            raise UserError(_("La rubrique de paie %s n'est pas paramétrée.") % code)
        return r


class KaRhRubriqueValeur(models.Model):
    """Valeur d'une rubrique à compter d'une date d'effet. Une valeur déjà appliquée à un bulletin confirmé n'est jamais
    modifiée : un changement de taux CNPS ou de barème crée une nouvelle ligne (RG-7.4)."""
    _name = 'ka.rh.rubrique.valeur'
    _description = 'Valeur historisée de rubrique'
    _order = 'date_effet desc'

    rubrique_id = fields.Many2one('ka.rh.rubrique', required=True, ondelete='cascade')
    date_effet = fields.Date(string="Date d'effet", required=True)
    taux = fields.Float(string='Taux / coefficient', digits=(8, 4), help='0.063 = 6,3 % ; 1.25 = majoration de 25 %')
    montant = fields.Float(string='Montant fixe', digits=(14, 0))
    plafond = fields.Float(string='Plafond mensuel', digits=(14, 0), help='0 = sans plafond')

    def write(self, vals):
        if {'taux', 'montant', 'plafond', 'date_effet'} & set(vals):
            for v in self:
                if self.env['ka.rh.bulletin'].search_count([('state', 'in', ('confirme', 'paye')),
                                                            ('periode', '>=', v.date_effet)]):
                    raise UserError(_("La valeur du %s a déjà servi à des bulletins confirmés : créez une nouvelle "
                                      "valeur avec sa date d'effet (RG-7.4).") % v.date_effet)
        return super().write(vals)


class KaRhItsTranche(models.Model):
    """Barème progressif mensuel de l'impôt sur les traitements et salaires (ordonnance n° 2023-719), actualisable à
    chaque loi de finances."""
    _name = 'ka.rh.its.tranche'
    _description = 'Tranche du barème ITS'
    _order = 'date_effet desc, borne_inf'

    date_effet = fields.Date(string="Date d'effet", required=True)
    borne_inf = fields.Float(string='De', digits=(14, 0), required=True)
    borne_sup = fields.Float(string='À', digits=(14, 0), help='0 = sans limite')
    taux = fields.Float(string='Taux', digits=(6, 4), required=True)

    @api.model
    def calculer(self, imposable, date):
        tranches = self.search([('date_effet', '<=', date)])
        if not tranches:
            return 0.0
        derniere = max(tranches.mapped('date_effet'))
        impot = 0.0
        for t in tranches.filtered(lambda x: x.date_effet == derniere).sorted('borne_inf'):
            haut = t.borne_sup or imposable
            if imposable > t.borne_inf:
                impot += (min(imposable, haut) - t.borne_inf) * t.taux
        return round(impot)


class KaRhRicf(models.Model):
    """Réduction d'impôt pour charges de famille : montant mensuel forfaitaire selon le nombre de parts."""
    _name = 'ka.rh.ricf'
    _description = "Réduction d'impôt pour charges de famille"
    _order = 'date_effet desc, parts'

    date_effet = fields.Date(string="Date d'effet", required=True)
    parts = fields.Float(string='Parts', digits=(4, 1), required=True)
    montant = fields.Float(string='Réduction mensuelle', digits=(14, 0), required=True)

    @api.model
    def reduction(self, parts, date):
        lignes = self.search([('date_effet', '<=', date), ('parts', '<=', parts)], order='date_effet desc, parts desc', limit=1)
        return lignes.montant


class KaRhTypeConge(models.Model):
    """Type de congé et sa règle d'acquisition (§ 7.2.4)."""
    _name = 'ka.rh.type.conge'
    _description = 'Type de congé'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    code = fields.Char(string='Code', required=True)
    name = fields.Char(string='Type de congé', required=True)
    acquisition = fields.Float(string='Acquisition mensuelle (jours)', digits=(4, 2),
                               help='Ex. 2,2 jours ouvrables par mois de travail effectif')
    deductible = fields.Boolean(string='Déduit du solde', default=True)
    remunere = fields.Boolean(string='Rémunéré', default=True)
    report = fields.Boolean(string='Report du solde non consommé', default=True)


class KaRhFerie(models.Model):
    """Jours fériés et chômés, exclus du décompte des congés pris (y compris fêtes mobiles)."""
    _name = 'ka.rh.ferie'
    _description = 'Jour férié'
    _order = 'date'

    date = fields.Date(string='Date', required=True)
    name = fields.Char(string='Fête', required=True)


class KaRhBaremeMission(models.Model):
    """Barème des indemnités de mission (per diem) selon la catégorie et la destination (§ 7.4.2)."""
    _name = 'ka.rh.bareme.mission'
    _description = 'Barème des indemnités de mission'
    _order = 'categorie_id, zone'

    categorie_id = fields.Many2one('ka.rh.categorie', string='Catégorie du collaborateur')
    zone = fields.Selection([('interieur', "Intérieur du pays"), ('abidjan', 'Abidjan / port'),
                             ('etranger', 'Étranger')], string='Destination', required=True, default='interieur')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    per_diem = fields.Monetary(string='Per diem / jour', required=True)
    hebergement = fields.Monetary(string='Hébergement / nuit')

    @api.model
    def taux(self, categorie, zone):
        b = self.search([('categorie_id', '=', categorie.id), ('zone', '=', zone)], limit=1) \
            or self.search([('categorie_id', '=', False), ('zone', '=', zone)], limit=1)
        return b


class KaRhCompetence(models.Model):
    """Référentiel de compétences, par famille de métiers (§ 7.6.3)."""
    _name = 'ka.rh.competence'
    _description = 'Compétence'
    _order = 'famille, name'

    name = fields.Char(string='Compétence', required=True)
    famille = fields.Selection([('production', 'Production'), ('maintenance', 'Maintenance'), ('securite', 'Sécurité'),
                                ('collecte', 'Collecte'), ('administration', 'Administration')],
                               string='Famille de métiers', default='production')


NIVEAUX = [('debutant', 'Débutant'), ('confirme', 'Confirmé'), ('expert', 'Expert'), ('acquis', 'Acquis')]
RANG = {'debutant': 1, 'acquis': 1, 'confirme': 2, 'expert': 3}


class KaRhCompetenceNiveau(models.Model):
    """Niveau atteint par un collaborateur sur une compétence du référentiel."""
    _name = 'ka.rh.competence.niveau'
    _description = 'Compétence du collaborateur'
    _order = 'competence_id'

    employe_id = fields.Many2one('ka.rh.employe', required=True, ondelete='cascade')
    competence_id = fields.Many2one('ka.rh.competence', string='Compétence', required=True)
    niveau = fields.Selection(NIVEAUX, string='Niveau', required=True, default='debutant')
    date = fields.Date(string='Mise à jour', default=fields.Date.context_today)
    origine = fields.Char(string='Origine', help='Session de formation ou entretien de carrière')

    @api.constrains('employe_id', 'competence_id')
    def _check_unique(self):
        for n in self:
            if self.search_count([('employe_id', '=', n.employe_id.id), ('competence_id', '=', n.competence_id.id)]) > 1:
                raise ValidationError(_('La compétence %s figure déjà sur la fiche.') % n.competence_id.name)
