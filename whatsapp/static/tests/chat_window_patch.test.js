import { describe, test } from "@odoo/hoot";
import { click, contains, start, startServer } from "@mail/../tests/mail_test_helpers";
import { Command, serverState } from "@web/../tests/web_test_helpers";
import { defineWhatsAppModels } from "@whatsapp/../tests/whatsapp_test_helpers";

describe.current.tags("desktop");
defineWhatsAppModels();

test("WhatsApp channel chat windows should have thread icon", async () => {
    const pyEnv = await startServer();
    const whatsappPartnerId = pyEnv["res.partner"].create({});
    pyEnv["discuss.channel"].create({
        name: "WhatsApp 1",
        channel_member_ids: [
            Command.create({ partner_id: serverState.partnerId }),
            Command.create({ partner_id: whatsappPartnerId }),
        ],
        channel_type: "whatsapp",
        whatsapp_partner_id: whatsappPartnerId,
    });
    await start();
    await click(".o_menu_systray i[aria-label='Messages']");
    await click(".o-mail-NotificationItem");
    await contains(".o-mail-ChatWindow-header .o-mail-ThreadIcon");
});
