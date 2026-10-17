/** @odoo-module **/
import { Component, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";

/** Rappel du contexte de travail dans la barre noire : « Dossier : PROD · Société : … » */
export class KaContext extends Component {
    static template = xml`
        <div class="o_ka_navctx">
            <span>Dossier : PROD</span>
            <span class="o_ka_dot">·</span>
            <span>Société : <t t-esc="societe"/></span>
        </div>`;
    static props = {};
    get societe() {
        const company = this.env.services.company;
        return (company && company.currentCompany && company.currentCompany.name) || "";
    }
}

registry.category("systray").add("kode_agri.context", { Component: KaContext }, { sequence: 1 });
