from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'kode_agri')
class TestDemonstration(TransactionCase):
    """Test de bout en bout : le chargement de la démonstration traverse les vrais flux de tous les modules.
    Une étape en échec signale un flux cassé : le message du rapport dit lequel."""

    def test_rapport_sans_echec(self):
        rapport = self.env['ir.config_parameter'].sudo().get_param('kode_agri.demo_rapport') or ''
        self.assertTrue(rapport, "le rapport de démonstration est absent : le chargement n'a pas eu lieu")
        echecs = [l for l in rapport.splitlines() if l.startswith('ÉCHEC')]
        self.assertFalse(echecs, 'Étapes de démonstration en échec :\n' + '\n'.join(echecs))

    def test_donnees_attendues(self):
        env = self.env
        self.assertEqual(env['ka.ticket'].search_count([('state', '=', 'valide')]), 5)
        self.assertEqual(env['ka.colis'].search_count([('state', '=', 'valide')]), 16)
        liberes = env['stock.lot'].search_count([('ka_est_colis', '=', True), ('ka_etat', '=', 'A')])
        self.assertEqual(liberes, 15, '15 colis TSR10 libérés ; le seizième reste en quarantaine (points blancs)')
        self.assertTrue(env['ka.contrat'].search([('state', '=', 'signee')]))
        self.assertTrue(env['ka.budget'].search([('state', '=', 'valide')]))
        dot = env['ka.immo.dotation'].search([('state', '=', 'comptabilisee')], limit=1)
        self.assertEqual(round(dot.total), 1_233_333)

    def test_ecrans_de_pilotage_calculent(self):
        """Les états calculés à l'ouverture ne doivent pas lever d'erreur sur les données de démonstration."""
        env = self.env
        for xmlid in ('kode_agri_gestion.kpi_1', 'kode_agri_gestion.pnl_1', 'kode_agri_gestion.treso_gl_1', 'kode_agri_gestion.ecart_1',
                      'kode_agri_gestion.cascade_1', 'kode_agri_compta.treso_1'):
            rec = env.ref(xmlid)
            rec.invalidate_recordset()
            rec.read(list(rec._fields))
