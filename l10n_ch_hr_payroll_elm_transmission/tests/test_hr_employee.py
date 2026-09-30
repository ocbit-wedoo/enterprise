# Part of Odoo. See LICENSE file for full copyright and licensing details.

from .common import TestSwissdecCommon
from odoo.tests import tagged
from odoo import Command


@tagged('post_install', 'post_install_l10n', '-at_install')
class TestHrEmployee(TestSwissdecCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_update_employee_details_with_hr_user(self):
        employee_ch = self.env['hr.employee'].create({
            'name': 'Test employee',
            'company_id': self.muster_ag_company.id,
        })
        hr_user = self.env['res.users'].create({
            'name': 'HR Officer',
            'login': 'hr_officer',
            'groups_id': [Command.set(self.env.ref('hr.group_hr_user').ids)],
        })
        employee_ch.with_user(hr_user).marital = 'married'
        self.assertEqual(employee_ch.marital, 'married')
