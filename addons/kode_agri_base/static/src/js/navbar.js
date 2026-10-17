/** @odoo-module **/
import { NavBar } from "@web/webclient/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

patch(NavBar.prototype, {
    setup() {
        super.setup(...arguments);
        this.kaCompany = useService("company");
    },
    get kaContext() {
        const company = this.kaCompany.currentCompany;
        return {
            dossier: "PROD",
            societe: company && company.name,
        };
    },
});
