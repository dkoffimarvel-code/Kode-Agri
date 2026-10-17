from datetime import date

from odoo.tests import TransactionCase, tagged

from odoo.addons.kode_agri_gestion.models.common import fmt_dec, fmt_int, fmt_par, fmt_signe
from odoo.addons.kode_agri_immo.models.immo import calcul_plan
from odoo.addons.kode_agri_vente.models.common import spec_ok


@tagged('post_install', '-at_install', 'kode_agri')
class TestCalculs(TransactionCase):
    """Règles de calcul pures : elles ne dépendent pas de la démonstration."""

    def test_plan_amortissement_lineaire(self):
        plan = calcul_plan(40_000_000, date(2025, 1, 1), 10, 'lineaire')
        self.assertEqual(len(plan), 120)
        self.assertEqual(plan[0][1], 333_333)
        self.assertEqual(plan[-1][2], 40_000_000, 'la dernière échéance solde exactement la valeur')

    def test_plan_amortissement_prorata_et_degressif(self):
        for methode in ('lineaire', 'degressif'):
            plan = calcul_plan(28_500_000, date(2026, 3, 15), 8, methode)
            self.assertEqual(plan[-1][2], 28_500_000, methode)
            self.assertTrue(all(p[1] > 0 for p in plan))

    def test_specifications(self):
        self.assertTrue(spec_ok('≥ 30', '≥ 30', 32))
        self.assertFalse(spec_ok('≥ 30', '≥ 30', 28))
        self.assertTrue(spec_ok('40 – 49', '40 – 49', 45))
        self.assertFalse(spec_ok('40 – 49', '40 – 49', 50))
        self.assertTrue(spec_ok('NAP', 'NAP', None))
        self.assertTrue(spec_ok('Selon client', 'Selon client', None))
        self.assertFalse(spec_ok('≤ 0,10', '≤ 0,10', 0.11))

    def test_formats_des_maquettes(self):
        self.assertEqual(fmt_int(28_400_000), '28 400 000')
        self.assertEqual(fmt_par(-318), '(318)')
        self.assertEqual(fmt_signe(1_600_000), '+ 1 600 000')
        self.assertEqual(fmt_dec(-2.5), '−2,5')


@tagged('post_install', '-at_install', 'kode_agri')
class TestRegles(TransactionCase):
    """Règles de gestion qui s'appliquent sur des enregistrements créés par le test."""

    def test_budget_valide_est_verrouille(self):
        from odoo.exceptions import UserError
        compte = self.env['account.account'].search([], limit=1)
        section = self.env['account.analytic.account'].search([('code', '=', 'ACH_FDT')], limit=1)
        bud = self.env['ka.budget'].create({'annee': 2031, 'ligne_ids': [(0, 0, {'account_id': compte.id, 'section_id': section.id, 'm01': 100})]})
        bud.action_valider()
        with self.assertRaises(UserError):
            bud.ligne_ids.write({'m01': 200})
        with self.assertRaises(UserError):
            bud.unlink()
        rev = bud.action_revision()
        self.assertEqual(self.env['ka.budget'].browse(rev['res_id']).state, 'preparation')

    def test_ventilation_somme_egale_total(self):
        partner = self.env['res.partner'].create({'name': 'Fournisseur test'})
        prod = self.env['product.product'].create({'name': 'Article test', 'type': 'consu'})
        dossier = self.env['ka.dossier.import'].create({
            'partner_id': partner.id, 'transitaire_id': partner.id,
            'line_ids': [(0, 0, {'product_id': prod.id, 'qty': 1, 'fob': v}) for v in (9_180_000, 3_240_000, 2_580_000)],
            'frais_ids': [(0, 0, {'type': 'transport', 'facture_ref': 'F1', 'montant': 1_871_250})]})
        dossier.action_ventiler()
        self.assertEqual(sum(dossier.line_ids.mapped('frais')), 1_871_250)
        self.assertEqual(dossier.cout_complet, 16_871_250)

    def test_dotations_de_la_maquette(self):
        self.assertEqual(sum(calcul_plan(v, date(2026, 1, 1), a, 'lineaire')[0][1] for v, a in ((40_000_000, 10), (54_000_000, 10), (43_200_000, 8))), 1_233_333)
