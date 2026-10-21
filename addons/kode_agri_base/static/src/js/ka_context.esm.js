/** @odoo-module **/
import { Component, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";

/** Libellé « ERP KODE » affiché à droite de la barre d'application, comme sur les maquettes. */
export class KaErp extends Component {
    static template = xml`<div class="o_ka_erp">ERP KODE</div>`;
    static props = {};
}

registry.category("systray").add("kode_agri.erp", { Component: KaErp }, { sequence: 1 });
