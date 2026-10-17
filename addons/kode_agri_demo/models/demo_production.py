import logging
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, models

_logger = logging.getLogger(__name__)


class KaDemoProduction(models.AbstractModel):
    _inherit = 'ka.demo'

    # ---- M4 : production et qualité ------------------------------------------------------------------------------------------
    def _m4_production(self):
        if self.env['ka.of'].search([('note', '=', 'DEMO')], limit=1):
            return 'déjà chargé'
        fdt = self._ref('kode_agri_planteur.product_fdt_hevea')
        quants = self.env['stock.quant'].search([('product_id', '=', fdt.id), ('quantity', '>', 0), ('location_id.usage', '=', 'internal')])
        if not quants:
            raise ValueError("aucun stock de fond de tasse : l'étape « tickets → réceptions » n'a pas abouti")
        lots = quants.lot_id
        for lot in lots:
            lot.ka_set_drc(60.0, 'Essai de démonstration')
        mel = self.env['ka.of'].create({
            'type': 'melange', 'note': 'DEMO', 'product_id': self._ref('kode_agri_production.product_mel_std').id, 'qty': sum(quants.mapped('quantity')),
            'mode_conso': 'auto', 'atelier': 'broyage',
            'lot_ids': [Command.create({'lot_id': q.lot_id.id, 'godets': 1 + i, 'qty': q.quantity, 'drc': 60, 'cout_kg': 615}) for i, q in enumerate(quants)]})
        mel.action_lancer()
        mel.action_consommer_fdt()
        prod = self.env['ka.of'].create({
            'type': 'production', 'note': 'DEMO', 'product_id': self._ref('kode_agri_production.product_tsr').id, 'grade_vise': 'TSR10',
            'melange_ids': [Command.create({'melange_of_id': mel.id, 'qty_humide': sum(quants.mapped('quantity'))})]})
        prod.action_lancer()
        sechoir = self._ref('kode_agri_production.wc_pc03_01')
        paniers = self.env['ka.panier']
        for k in range(1, 9):
            p = self.env['ka.panier'].create({'of_id': prod.id, 'name': str(k), 'sechoir_id': sechoir.id, 'cycle_min': 180, 'nb_pains': 8, 'nb_balles': 72,
                                              'temp_bruleur1': 215, 'temp_bruleur2': 218, 'temp_balles': 92})
            p.action_valider()
            paniers |= p
        colis = self.env['ka.colis']
        for k in range(16):
            c = self.env['ka.colis'].create({'of_id': prod.id, 'panier_line_ids': [Command.create({'panier_id': paniers[k // 2].id, 'balles': 36})]})
            c.action_valider()
            colis |= c
        # contrôle panier P0/PRI (non bloquant, sans impact stock)
        qcp = self.env['ka.qc.panier'].create({'panier_id': paniers[0].id, 'p0': 32, 'pri': 54})
        qcp.action_valider()
        # spécifications laboratoire → classement TSR10 → reclassement 1 pour 1
        resultats = {'p0': 32, 'pri': 54, 'ml': 70, 'imp': 0.08, 'azote': 0.45, 'cendres': 0.5, 'vm': 0.6}
        nouveaux = self.env['stock.lot']
        for c in colis[:15]:
            spec = self.env['ka.spec'].create({'lot_id': c.lot_id.id})
            for l in spec.line_ids:
                l.resultat = resultats[l.test]
            spec.action_valider()
            nouveaux |= spec.lot_id
        # le seizième colis présente un défaut de texture (points blancs) : déclassé à la production
        dernier = colis[15]
        spec = self.env['ka.spec'].create({'lot_id': dernier.lot_id.id, 'texture': 'points_blancs'})
        for l in spec.line_ids:
            l.resultat = resultats[l.test]
        spec.action_valider()
        # contrôle à libération : les 15 colis conformes passent au stock libre (statut A)
        lib = self.env['ka.qc.liberation'].create({'line_ids': [Command.create({'lot_id': l.id}) for l in nouveaux]})
        lib.action_valider_conteneur()
        # contrôle de réception et essai DRC
        ticket = self.env['ka.ticket'].search([], limit=1)
        if ticket and ticket.ka_qc_ids:
            ticket.ka_qc_ids[:1].line_ids[:1].poids = 3.5
        essai = self.env['ka.drc.essai'].create({'lot_id': lots[0].id, 'echantillon_g': 500, 'poids_sec_g': 298})
        essai.action_enregistrer()
        return '%d lots FDT, 1 mélange, 1 OF, %d paniers, %d colis (15 libérés TSR10, 1 en points blancs)' % (len(lots), len(paniers), len(colis))
