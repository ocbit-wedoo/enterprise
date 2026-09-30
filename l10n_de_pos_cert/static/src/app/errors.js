/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

export class TaxError extends Error {
    constructor(product) {
        super(
            _t("The tax for the product '%(productName)s' with id %(productId)s is not allowed.", {
                productName: product.display_name,
                productId: product.id,
            })
        );
    }
}

function taxErrorHandler(env, _error, originalError) {
    if (originalError instanceof TaxError) {
        env.services.dialog.add(AlertDialog, {
            title: _t("Tax Error"),
            body: originalError.message,
        });
        return true;
    }
}

registry.category("error_handlers").add("taxErrorHandler", taxErrorHandler);
