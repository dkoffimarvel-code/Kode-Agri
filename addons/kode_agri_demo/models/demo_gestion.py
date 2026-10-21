from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, models

from odoo.addons.kode_agri_gestion.models.common import SECTIONS, plan_col, plan_de

# Répartition par section et compte général du coût de la campagne (grade TSR10), en FCFA — écran 9.1
COUTS = {
    'ACH_FDT': [('601100', 28_400_000, True)],
    'USINAGE': [('613200', 5_520_000, False), ('641100', 3_680_000, False)],
    'FOB': [('624100', 2_600_000, False)],
    'AFV': [('627100', 900_000, False)],
    'ADMIN': [('641200', 1_000_000, False)],
}
NOTES = {'ACH_FDT': 'Hausse du prix bord champ', 'USINAGE': 'Surcoût énergie', 'FOB': 'Négociation transitaire',
         'AFV': 'Écarts de change', 'ADMIN': 'Maîtrise des frais de siège'}


class KaDemoGestion(models.AbstractModel):
    _inherit = 'ka.demo'

    def _compte_analytique(self, code, nom, plan_xmlid):
        acc = self._analytique(code)
        return acc or self.env['account.analytic.account'].create({'name': nom, 'code': code, 'plan_id': self._ref(plan_xmlid).id})

    def _ligne_analytique(self, jour, accounts, compte, montant, qty=0.0, nom='Démo'):
        """Une ligne analytique rattachée à plusieurs plans (colonne par plan), sur un compte général."""
        vals = {'name': nom, 'date': jour, 'amount': -montant, 'general_account_id': compte.id, 'unit_amount': qty, 'company_id': self.env.company.id}
        for acc in accounts:
            if acc:
                vals[plan_col(plan_de(acc))] = acc.id
        vals.setdefault('account_id', accounts[0].id)
        return self.env['account.analytic.line'].create(vals)

    def _m9_gestion(self):
        if self.env['ka.budget'].search([('annee', '=', date.today().year)], limit=1):
            return 'déjà chargé'
        today = date.today()
        grade10 = self._analytique('TSR10')
        grade20 = self._analytique('TSR20')
        site = self._analytique('U01')
        n = 0
        # 1. écritures analytiques de la campagne en cours et de la précédente (alimentent cascade, KPI, budget, écarts)
        for annee, facteur in ((today.year - 1, 0.95), (today.year, 1.0)):
            camp = self._compte_analytique(str(annee), str(annee), 'kode_agri_gestion.plan_campagne')
            mois_max = 12 if annee < today.year else max(today.month, 1)
            for code, postes in COUTS.items():
                section = self._analytique(code)
                for compte_code, total, avec_qte in postes:
                    compte = self._compte(compte_code)
                    for m in range(1, mois_max + 1):
                        part = total * facteur / mois_max
                        self._ligne_analytique(date(annee, m, 15), [section, grade10, camp, site], compte, part, qty=(part / 615.0 if avec_qte else 0.0),
                                               nom='%s %s' % (dict((c, nm) for c, nm, _e in SECTIONS)[code], date(annee, m, 1).strftime('%m/%Y')))
                        self._ligne_analytique(date(annee, m, 16), [section, grade20, camp, site], compte, part * 0.35, nom='%s TSR20' % code)
                        n += 2
        # 2. budget de l'année : maquette générée depuis le réalisé N-1, soumis puis validé (verrouillé), puis une révision en préparation
        bud = self.env['ka.budget'].create({'annee': today.year, 'version': 'initial', 'axe_croise': 'Grade TSR10 / campagne %s' % today.year})
        bud.action_generer_maquette()
        bud.action_soumettre()
        bud.action_valider()
        bud.action_revision()
        for code, texte in NOTES.items():
            self.env['ka.ecart.note'].create({'annee': today.year, 'section_code': code, 'texte': texte})
        # 3. bon à budgétiser CAPEX complet (circuit de signature jusqu'au conseil d'administration)
        bab = self.env['ka.bab'].create({'intitule': 'Ligne de séchage n° 3 — site Anguédédou', 'nature': 'Matériel industriel',
                                         'account_id': self._compte('2411100').id, 'dotation': 185_000_000, 'periode': '%s — mise en service T3' % today.year,
                                         'budget_id': bud.id})
        bab.action_soumettre()
        bab.action_viser()
        bab.action_approuver()
        bab.action_autoriser()
        bab.action_consulter()
        # 4. unités d'œuvre du camion VH0001 le mois dernier : clés 45 % / 30 % / 25 %
        mois = today.replace(day=1) - relativedelta(months=1)
        camion = self._compte_analytique('VH0001', 'VH0001 — Camion de transport', 'kode_agri_gestion.plan_equip')
        for code, montant in (('602200', 4_200_000), ('602400', 1_800_000), ('615500', 900_000)):
            self._ligne_analytique(mois.replace(day=20), [camion], self._compte(code), montant, nom='Camion VH0001')
        recepteurs = {'ACH_FDT': (182, 1339), 'USINAGE': (96, 918), 'FOB': (124, 721)}
        for code, (q1, q2) in recepteurs.items():
            for jour, q in ((1, q1), (15, q2)):
                self.env['ka.uo'].create({'date': mois.replace(day=jour), 'emetteur_id': camion.id, 'unite': 'km',
                                          'recepteur_id': self._analytique(code).id, 'quantite': q})
        rep = self.env['ka.repartition'].create({'emetteur_id': camion.id, 'periode': mois})
        rep.action_calculer_cles()
        return '%d écritures analytiques, budget %s validé + révision, bon CAPEX autorisé, répartition VH0001 (clés %s)' % (
            n, bud.name, ' / '.join('%d %%' % round(c.pct) for c in rep.cle_ids))
