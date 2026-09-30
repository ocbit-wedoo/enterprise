# Part of Odoo. See LICENSE file for full copyright and licensing details.
from datetime import date, datetime
import base64

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestAcerta(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.belgium = cls.env.ref('base.be')

        cls.belgian_company = cls.env['res.company'].create({
            'name': 'My Belgian Company - Test',
            'country_id': cls.env.ref('base.be').id,
            'acerta_code': '1234567'
        })

        cls.resource_calendar = cls.env['resource.calendar'].create({
            'name': 'Test Calendar',
            'company_id': cls.belgian_company.id,
            'hours_per_day': 7.6,
            'tz': "Europe/Brussels",
            'two_weeks_calendar': False,
            'hours_per_week': 38,
            'full_time_required_hours': 38
        })

        cls.employee_acerta = cls.env['hr.employee'].create({
            'name': 'Acerta employee',
            'company_id': cls.belgian_company.id,
            'resource_calendar_id': cls.resource_calendar.id,
        })

        cls.contract_acerta = cls.env['hr.contract'].create({
            'name': 'Acerta contract',
            'employee_id': cls.employee_acerta.id,
            'company_id': cls.belgian_company.id,
            'resource_calendar_id': cls.resource_calendar.id,
            'wage': 2000,
            'date_start': date(2026, 1, 1),
            'acerta_code': '3344',
            'state': 'open',
        })

        cls.work_entry_type = cls.env['hr.work.entry.type'].create({
            'name': 'Sick time off',
            'code': 'SICK110',
            'acerta_code': '050',
        })

        cls.sick_time_off_type = cls.env['hr.leave.type'].create({
            'name': 'Sick Time Off',
            'company_id': cls.belgian_company.id,
            'requires_allocation': 'no',
            'work_entry_type_id': cls.work_entry_type.id,
        })

    def test_acerta_sick_time_off_overlapping_weekend(self):
        self.env.company = self.belgian_company
        self.env['hr.leave'].create({
            'name': 'Sick time off',
            'employee_id': self.employee_acerta.id,
            'company_id': self.belgian_company.id,
            'holiday_status_id': self.sick_time_off_type.id,
            'request_date_from': '2026-08-07',
            'request_date_to': '2026-08-10',
        }).action_validate()

        self.employee_acerta.contract_id._generate_work_entries(datetime(2026, 8, 6, 0, 0, 0),
                                                                datetime(2026, 8, 11, 23, 59, 59))

        acerta_report = self.env['l10n.be.hr.payroll.export.acerta'].create({
            'company_id': self.belgian_company.id,
            'period_start': date(2026, 8, 1),
            'period_stop': date(2026, 8, 31),
            'reference_month': '8',
            'reference_year': 2026,
        })

        acerta_report.action_populate()
        acerta_report.action_export_file()
        content = base64.b64decode(acerta_report.export_file).decode('utf-8')

        expected_line_sat = 'KLX1123456700000000000003344   08/08/2026  0050  0000'
        expected_line_sun = 'KLX1123456700000000000003344   09/08/2026  0050  0000'

        self.assertIn(expected_line_sat, content)
        self.assertIn(expected_line_sun, content)
