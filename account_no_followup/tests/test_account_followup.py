from freezegun import freeze_time
from unittest.mock import patch
from odoo.tests import tagged
from odoo.addons.account_followup.tests.test_account_followup import TestAccountFollowupReports


@tagged('post_install', '-at_install')
class TestNoFollowupAccountFollowupReports(TestAccountFollowupReports):

    def test_followup_line_and_status(self):
        followup_line = self.create_followup(delay=-10)

        self.create_invoice('2022-01-02')

        with freeze_time('2022-02-03'):
            aml_ids = self.partner_a.unreconciled_aml_ids

            # Exclude every unreconciled invoice line.
            aml_ids.no_followup = True
            # Every unreconciled invoice line is excluded, so the result should be `no_action_needed`.
            self.assertPartnerFollowup(self.partner_a, 'no_action_needed', followup_line)

            # It resets if we don't exclude them anymore.
            aml_ids.no_followup = False
            self.assertPartnerFollowup(self.partner_a, 'in_need_of_action', followup_line)

    def test_automatic_followup_no_followup_invoice_not_attached(self):
        followup_line = self.env['account_followup.followup.line'].create({
            'company_id': self.env.company.id,
            'name': 'First Reminder',
            'delay': 15,
            'send_email': True,
        })
        invoice = self._create_invoice(invoice_date='2016-01-01', post=True)

        self.assertPartnerFollowup(self.partner_a, 'in_need_of_action', followup_line)

        send_wizard = self.env['account.move.send.wizard']\
            .with_context(active_model='account.move', active_ids=invoice.ids)\
            .create({'sending_methods': ['manual']})
        send_wizard.action_send_and_print()

        # Simulate toggling "No Follow-Up" in the customer statement.
        invoice.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable').no_followup = True

        self.partner_a._compute_unpaid_invoices()
        with patch.object(self.env.registry['account.report'], 'export_to_pdf', autospec=True, side_effect=lambda *args, **kwargs: {'file_name': 'fake_partner_ledger.pdf', 'file_content': b'', 'file_type': 'pdf'}):
            self.partner_a.action_manually_process_automatic_followups()

        sent_attachments = self.env['mail.message'].search([
            ('partner_ids', '=', self.partner_a.id),
        ], order='id desc', limit=1).attachment_ids
        self.assertNotIn(invoice._get_invoice_report_filename(), sent_attachments.mapped('name'))

    def test_manual_followup_no_followup_invoice_not_attached(self):
        mail_template = self.env['mail.template'].create({
            'name': 'reminder',
            'model_id': self.env['ir.model']._get_id('res.partner'),
        })

        self.env['account_followup.followup.line'].create({
            'company_id': self.env.company.id,
            'name': 'First Reminder',
            'delay': 15,
            'send_email': True,
            'mail_template_id': mail_template.id,
        })
        invoice = self._create_invoice(invoice_date='2016-01-01', post=True)

        invoice_attachment = self.env['ir.attachment'].create({
            'name': 'invoice_attachment.pdf',
            'res_id': invoice.id,
            'res_model': 'account.move',
            'res_field': 'invoice_pdf_report_file',
            'datas': 'test',
            'type': 'binary',
        })
        invoice._message_set_main_attachment_id(invoice_attachment)

        # Simulate toggling "No Follow-Up" in the customer statement.
        invoice.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable').no_followup = True

        wizard = self.env['account_followup.manual_reminder'].with_context(
            active_model='res.partner',
            active_ids=self.partner_a.ids,
        ).create({})

        self.assertNotIn(
            invoice_attachment.id,
            wizard.attachment_ids.ids,
            "The invoice marked as No Follow-Up should not be part of the wizard attachments list.",
        )

        options = wizard._get_wizard_options()
        options['followup_line'] = self.partner_a.followup_line_id or self.partner_a._get_first_followup_level()
        with patch.object(self.env.registry['account.report'], 'export_to_pdf', autospec=True, side_effect=lambda *args, **kwargs: {'file_name': 'fake_partner_ledger.pdf', 'file_content': b'', 'file_type': 'pdf'}):
            self.partner_a._get_followup_attachments(options)

        self.assertNotIn(invoice_attachment.id, options['attachment_ids'])
