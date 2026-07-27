# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from odoo.exceptions import UserError

from odoo.addons.hr_timesheet.tests.test_timesheet import TestCommonTimesheet


class TestAnalyticLine(TestCommonTimesheet):
    def test_check_timesheet_unit_amount(self):
        AccountAnalyticLine = self.env['account.analytic.line'].with_context(default_name='/')
        timesheet, analytic_line = AccountAnalyticLine.create([
            {
                'project_id': self.project_customer.id,
                'employee_id': self.empl_employee.id,
                'unit_amount': 1,
            },
            {
                'account_id': self.project_customer.account_id.id,
                'unit_amount': 1000000,
            },
        ])
        self.assertTrue(timesheet.is_timesheet, "The analytic line created should be a timesheet.")
        for value in (1000000, -1000000):
            with self.assertRaisesRegex(UserError, "You can't encode numbers with more than six digits."):
                AccountAnalyticLine.create({
                    'project_id': self.project_customer.id,
                    'employee_id': self.empl_employee.id,
                    'unit_amount': value,
                })
            with self.assertRaisesRegex(UserError, "You can't encode numbers with more than six digits."):
                timesheet.unit_amount = value

        self.assertFalse(analytic_line.is_timesheet, "The analytic line created should not be a timesheet since no project is set.")
        self.assertEqual(analytic_line.unit_amount, 1000000, "The user can enter a number with more than 6 digits for the analytic line which is not a timesheet.")
        analytic_line.unit_amount = 1000005
        self.assertEqual(analytic_line.unit_amount, 1000005, "The user can always alter the analytic to put the number he wants since it is not a timesheet.")

    def test_timesheet_unavailabilities(self):
        """
        Test that unavailabilities are based on current user's calendar if no groupby is provided
        """

        calendar_emp = self.env['resource.calendar'].create({
            'name': 'Monday Only Calendar',
            'attendance_ids': [
                (0, 0, {'name': 'Monday', 'dayofweek': '0', 'hour_from': 8, 'hour_to': 16, 'day_period': 'morning'}),
            ],
        })

        test_user = self.env['res.users'].create({
            'name': 'Test Employee User',
            'login': 'test_emp_user',
            'groups_id': [(4, self.env.ref('base.group_user').id)],
        })

        self.env['hr.employee'].create({
            'name': 'Test Employee',
            'user_id': test_user.id,
            'resource_calendar_id': calendar_emp.id,
        })

        start_date = '2026-04-14'
        end_date = '2026-04-15'

        unavailabilities = self.env['account.analytic.line'].with_user(test_user).with_context(get_current_user_unavailable_dates=True).grid_unavailability(
            start_date=start_date,
            end_date=end_date,
            groupby=''
        )

        self.assertIn(False, unavailabilities, "The result should contain the key False when no groupby is used.")
        unavailable_dates = unavailabilities[False]
        expected_dates = [date(2026, 4, 14), date(2026, 4, 15)]

        for d in expected_dates:
            self.assertIn(d, unavailable_dates, f"Date {d} should be marked as unavailable for this employee.")
