# -*- coding: utf-8 -*-
from odoo import models


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    def _get_all_reconcilable_account_ids(self):
        ids = super()._get_all_reconcilable_account_ids()
        categories = self.env['product.category'].search([
            '|',
            ('property_stock_account_input_categ_id', '!=', False),
            ('property_stock_account_output_categ_id', '!=', False)
        ])
        accounts = (categories.mapped('property_stock_account_input_categ_id') +
                    categories.mapped('property_stock_account_output_categ_id'))
        if accounts:
            return [id for id in ids if id not in accounts.ids]
        return ids
