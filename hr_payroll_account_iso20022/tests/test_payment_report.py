from odoo.addons.hr_payroll.tests.common_payment_report import TestPaymentReportBase
from odoo.tests.common import tagged


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestPaymentReportCH(TestPaymentReportBase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({
            'country_id': cls.env.ref('base.ch').id,
        })

    def test_payslip_payment_report_default(self):
        action = self.payslip.action_payslip_payment_report()
        self.assertEqual(
            action['context']['default_export_format'],
            'iso20022_ch',
        )

    def test_payrun_payment_report_default(self):
        action = self.payrun.action_payment_report()
        self.assertEqual(
            action['context']['default_export_format'],
            'iso20022_ch',
        )


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestPaymentReportSepa(TestPaymentReportBase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_de = cls.env['res.company'].create({
            'name': 'Company DE',
            'country_id': cls.env.ref('base.de').id,
            'currency_id': cls.env.ref('base.EUR').id,
        })
        cls.employee.company_id = cls.company_de
        cls.contract.company_id = cls.company_de
        cls.payslip.company_id = cls.company_de
        cls.payrun.company_id = cls.company_de

    def test_payslip_payment_report_default(self):
        action = self.payslip.with_company(self.company_de).action_payslip_payment_report()
        self.assertEqual(
            action['context']['default_export_format'],
            'sepa',
        )

    def test_payrun_payment_report_default(self):
        action = self.payrun.with_company(self.company_de).action_payment_report()
        self.assertEqual(
            action['context']['default_export_format'],
            'sepa',
        )
