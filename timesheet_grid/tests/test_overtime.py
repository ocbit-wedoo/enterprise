# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime
from dateutil.relativedelta import relativedelta

from odoo.osv import expression
from odoo.tests import HttpCase, tagged


@tagged('-at_install', 'post_install')
class TestOvertime(HttpCase):
    def _last_week_wednesday_date(self):
        today = datetime.today()
        day_of_week = today.weekday()
        days_until_previous_wed = (day_of_week + 7 - 2) % 7
        days_to_last_weekWed = 7 + days_until_previous_wed if day_of_week >= 2 else days_until_previous_wed
        last_week_wednesday_date = today - relativedelta(days=days_to_last_weekWed)
        return last_week_wednesday_date

    def test_overtime(self):
        """ Check that total overtime is shown and highlighted """
        calendar = self.env['resource.calendar'].create({
            'name': 'Off on Wednesday, Saturday and Sunday',
            'tz': 'UTC',
            'hours_per_day': 8.0,
            'attendance_ids': [
                (0, 0, {'name': 'Monday Morning', 'dayofweek': '0', 'hour_from': 8, 'hour_to': 12, 'day_period': 'morning'}),
                (0, 0, {'name': 'Monday Lunch', 'dayofweek': '0', 'hour_from': 12, 'hour_to': 13, 'day_period': 'lunch'}),
                (0, 0, {'name': 'Monday Afternoon', 'dayofweek': '0', 'hour_from': 13, 'hour_to': 17, 'day_period': 'afternoon'}),
                (0, 0, {'name': 'Tuesday Morning', 'dayofweek': '1', 'hour_from': 8, 'hour_to': 12, 'day_period': 'morning'}),
                (0, 0, {'name': 'Tuesday Lunch', 'dayofweek': '1', 'hour_from': 12, 'hour_to': 13, 'day_period': 'lunch'}),
                (0, 0, {'name': 'Tuesday Afternoon', 'dayofweek': '1', 'hour_from': 13, 'hour_to': 17, 'day_period': 'afternoon'}),
                (0, 0, {'name': 'Thursday Morning', 'dayofweek': '3', 'hour_from': 8, 'hour_to': 12, 'day_period': 'morning'}),
                (0, 0, {'name': 'Thursday Lunch', 'dayofweek': '3', 'hour_from': 12, 'hour_to': 13, 'day_period': 'lunch'}),
                (0, 0, {'name': 'Thursday Afternoon', 'dayofweek': '3', 'hour_from': 13, 'hour_to': 17, 'day_period': 'afternoon'}),
                (0, 0, {'name': 'Friday Morning', 'dayofweek': '4', 'hour_from': 8, 'hour_to': 12, 'day_period': 'morning'}),
                (0, 0, {'name': 'Friday Lunch', 'dayofweek': '4', 'hour_from': 12, 'hour_to': 13, 'day_period': 'lunch'}),
                (0, 0, {'name': 'Friday Afternoon', 'dayofweek': '4', 'hour_from': 13, 'hour_to': 17, 'day_period': 'afternoon'}),
            ]
        })

        employee = self.env['hr.employee'].create({
            'name': 'Test Employee',
            'resource_calendar_id': calendar.id,
            'employee_type': 'freelance',
        })

        project = self.env['project.project'].create({
            'name': 'Test Project',
        })
        Timesheet = self.env['account.analytic.line']
        Timesheet.create({
            'project_id': project.id,
            'employee_id': employee.id,
            'date': self._last_week_wednesday_date().date(),
            'unit_amount': 8.0,
        })

        original_search = Timesheet._search

        def mock_search(self, domain, *args, **kwargs):
            additional_domain = [('employee_id', '=', employee.id), ('project_id', '=', project.id)]
            domain = expression.AND([domain, additional_domain])
            return original_search(domain, *args, **kwargs)

        self.patch(self.registry['account.analytic.line'], "_search", mock_search)
        self.start_tour('/odoo', 'timesheet_overtime', login='admin')

    def test_flexible_overtime_positive_utc_offset(self):
        """ Overtime for flexible schedules must not be inflated by timezone offset """
        calendar = self.env['resource.calendar'].create({
            'name': 'Flexible 20h',
            'tz': 'Europe/Brussels',
            'flexible_hours': True,
            'hours_per_day': 4.0,
            'full_time_required_hours': 20.0,
        })

        employee = self.env['hr.employee'].create({
            'name': 'Brussels Employee',
            'resource_calendar_id': calendar.id,
            'employee_type': 'freelance',
            'tz': 'Europe/Brussels',
        })

        result = employee.get_timesheet_and_working_hours_for_employees('2021-03-29', '2021-04-04')
        self.assertEqual(result[employee.id]['units_to_work'], 20.0)
