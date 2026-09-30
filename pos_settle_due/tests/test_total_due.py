# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime
from unittest.mock import patch

import odoo
from odoo import models
from odoo.addons.point_of_sale.tests.common import TestPointOfSaleCommon


@odoo.tests.tagged('post_install', '-at_install')
class TestPointOfSaleFlow(TestPointOfSaleCommon):

    def _create_open_charges(self, partner, dated_amounts):
        """ Posted receivable lines in the PoS journal, like the pay later
        charges of old sessions (no date_maturity either). Oldest first. """
        receivable = partner.property_account_receivable_id
        moves = self.env['account.move'].create([{
            'journal_id': self.pos_config.journal_id.id,
            'date': date,
            'line_ids': [
                (0, 0, {'account_id': receivable.id, 'partner_id': partner.id, 'debit': amount}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id, 'credit': amount}),
            ],
        } for date, amount in dated_amounts])
        moves.action_post()
        return moves.line_ids.filtered(lambda line: line.account_id == receivable).sorted('date')

    def _close_session_spying_reconciliation(self, session):
        """ Close the session; return every line handed to _reconcile_plan. """
        MoveLine = self.env.registry['account.move.line']
        original = MoveLine._reconcile_plan
        involved = self.env['account.move.line']

        def flatten(node):
            if isinstance(node, models.BaseModel):
                return node
            return sum((flatten(child) for child in node), self.env['account.move.line'])

        def spy(model, reconciliation_plan):
            nonlocal involved
            involved |= flatten(reconciliation_plan)
            return original(model, reconciliation_plan)

        with patch.object(MoveLine, '_reconcile_plan', spy):
            session.action_pos_session_closing_control()
        return involved

    def test_settle_due_reconciles_only_the_oldest_open_items(self):
        """ Settling a due pays the oldest open items first, and the close must
        not load the customer's other open items to do so. """
        oldest, middle, newest = self._create_open_charges(
            self.partner1, [('2024-01-10', 30), ('2024-02-10', 20), ('2024-03-10', 10)])

        self.pos_config.open_ui()
        session = self.pos_config.current_session_id
        # settle 25: an empty order paid by bank, credited on the customer account
        order = self.PosOrder.create({
            'company_id': self.env.company.id,
            'session_id': session.id,
            'partner_id': self.partner1.id,
            'pricelist_id': self.pos_config.pricelist_id.id,
            'amount_paid': 0.0,
            'amount_total': 0.0,
            'amount_tax': 0.0,
            'amount_return': 0.0,
        })
        order.add_payment({'pos_order_id': order.id, 'payment_method_id': self.bank_payment_method.id, 'amount': 25.0})
        order.add_payment({'pos_order_id': order.id, 'payment_method_id': self.credit_payment_method.id, 'amount': -25.0})
        order.action_pos_order_paid()

        involved = self._close_session_spying_reconciliation(session)

        self.assertEqual(session.state, 'closed')
        self.assertEqual(oldest.amount_residual, 5.0)
        self.assertEqual(middle.amount_residual, 20.0)
        self.assertEqual(newest.amount_residual, 10.0)
        self.assertIn(oldest, involved)
        self.assertNotIn(middle, involved, "open items beyond the settled amount must not be loaded")
        self.assertNotIn(newest, involved, "open items beyond the settled amount must not be loaded")

    def test_pay_later_charges_alone_do_not_load_open_items(self):
        """ A session that only adds to the customer's due has nothing to
        reconcile: its close must not load the open items at all. """
        charges = self._create_open_charges(self.partner1, [('2024-01-10', 30), ('2024-02-10', 20)])

        self.pos_config.open_ui()
        session = self.pos_config.current_session_id
        order = self.PosOrder.create({
            'company_id': self.env.company.id,
            'session_id': session.id,
            'partner_id': self.partner1.id,
            'lines': [(0, 0, {
                'name': "OL/0001",
                'product_id': self.product3.id,
                'price_unit': 10,
                'discount': 0,
                'qty': 1,
                'tax_ids': [[6, False, []]],
                'price_subtotal': 10,
                'price_subtotal_incl': 10,
            })],
            'pricelist_id': self.pos_config.pricelist_id.id,
            'amount_paid': 0.0,
            'amount_total': 10.0,
            'amount_tax': 0.0,
            'amount_return': 0.0,
        })
        order.add_payment({'pos_order_id': order.id, 'payment_method_id': self.credit_payment_method.id, 'amount': 10.0})
        order.action_pos_order_paid()

        involved = self._close_session_spying_reconciliation(session)

        self.assertEqual(session.state, 'closed')
        self.assertEqual(charges.mapped('amount_residual'), [30.0, 20.0])
        self.assertFalse(charges & involved, "nothing can be reconciled, the open items must not be loaded")

    def test_invoicing_after_closing_session(self):
        """ Test that an invoice can be created after the session is closed """
        # create customer account payment method
        self.customer_account_payment_method = self.env['pos.payment.method'].create({
            'name': 'Customer Account',
            'split_transactions': True,
        })

        self.product1 = self.env['product.product'].create({
            'name': 'Product A',
            'is_storable': True,
            'categ_id': self.env.ref('product.product_category_all').id,
        })
        self.partner1.write({'parent_id': self.env['res.partner'].create({'name': 'Parent'}).id})

        # add customer account payment method to pos config
        self.pos_config.write({
            'payment_method_ids': [(4, self.customer_account_payment_method.id, 0)],
        })
        # change the currency of PoS config
        self.other_currency = self.setup_other_currency("EUR", rounding=0.001, rates=[(datetime.today().date(), 0.5)])
        self.pos_config.journal_id.write({
            'currency_id': self.other_currency.id
        })
        other_pricelist = self.env['product.pricelist'].create({
            'name': 'Public Pricelist Other',
            'currency_id': self.other_currency.id,
        })
        self.pos_config.write({
            'pricelist_id': other_pricelist.id,
            'available_pricelist_ids': [(6, 0, other_pricelist.ids)],
        })
        self.pos_config.open_ui()
        current_session = self.pos_config.current_session_id

        # create pos order
        order = self.PosOrder.create({
            'company_id': self.env.company.id,
            'session_id': current_session.id,
            'partner_id': self.partner1.id,
            'lines': [(0, 0, {
                'name': "OL/0001",
                'product_id': self.product1.id,
                'price_unit': 6,
                'discount': 0,
                'qty': 1,
                'tax_ids': [[6, False, []]],
                'price_subtotal': 6,
                'price_subtotal_incl': 6,
            })],
            'pricelist_id': self.pos_config.pricelist_id.id,
            'amount_paid': 6.0,
            'amount_total': 6.0,
            'amount_tax': 0.0,
            'amount_return': 0.0,
        })

        # pay for the order with customer account
        payment_context = {"active_ids": order.ids, "active_id": order.id}
        order_payment = self.PosMakePayment.with_context(**payment_context).create({
            'amount': 2.0,
            'payment_method_id': self.cash_payment_method.id
        })
        order_payment.with_context(**payment_context).check()

        payment_context = {"active_ids": order.ids, "active_id": order.id}
        order_payment = self.PosMakePayment.with_context(**payment_context).create({
            'amount': 4.0,
            'payment_method_id': self.customer_account_payment_method.id
        })
        order_payment.with_context(**payment_context).check()

        # close session
        current_session.action_pos_session_closing_control()

        accounting_partner = self.env['res.partner']._find_accounting_partner(self.partner1)
        self.assertEqual(accounting_partner.total_due, 8.0)

        # create invoice
        order.action_pos_order_invoice()
        self.assertEqual(accounting_partner.total_due, 8.0)

        # get journal entry that does the reverse payment, it the ref must contains Reversal
        reverse_payment = self.env['account.move'].search([('ref', 'ilike', "Reversal")])
        original_payment = self.env['account.move'].search([('ref', '=', current_session.display_name)])
        original_customer_payment_entry = original_payment.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
        reverser_customer_payment_entry = reverse_payment.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
        # check that both use the same account
        self.assertEqual(len(reverser_customer_payment_entry), 2)
        self.assertEqual(len(original_customer_payment_entry), 2)
        self.assertTrue(order.account_move.line_ids.partner_id == self.partner1.commercial_partner_id)
        self.assertEqual(reverser_customer_payment_entry[0].balance, -4.0)
        self.assertEqual(reverser_customer_payment_entry[1].balance, -8.0)
        self.assertEqual(reverser_customer_payment_entry[0].amount_currency, -2.0)
        self.assertEqual(reverser_customer_payment_entry[1].amount_currency, -4.0)
        self.assertEqual(original_customer_payment_entry.account_id.id, reverser_customer_payment_entry.account_id.id)
        self.assertEqual(reverser_customer_payment_entry.partner_id, original_customer_payment_entry.partner_id)

    def test_get_total_due_in_pos_currency(self):
        """ get_total_due must return an amount expressed in the PoS currency.

        The accounting due (res.partner.total_due) is in company currency and
        must be converted, while the pay later payments of the still open
        sessions are already in the PoS currency and must not be converted.
        """
        self.customer_account_payment_method = self.env['pos.payment.method'].create({
            'name': 'Customer Account',
            'split_transactions': True,
        })
        self.product1 = self.env['product.product'].create({
            'name': 'Product A',
            'is_storable': True,
            'categ_id': self.env.ref('product.product_category_all').id,
        })
        self.pos_config.write({
            'payment_method_ids': [(4, self.customer_account_payment_method.id, 0)],
        })
        # PoS runs in another currency than the company one: 1 company = 0.5 other
        self.other_currency = self.setup_other_currency("EUR", rounding=0.01, rates=[(datetime.today().date(), 0.5)])
        self.pos_config.journal_id.write({
            'currency_id': self.other_currency.id
        })
        other_pricelist = self.env['product.pricelist'].create({
            'name': 'Public Pricelist Other',
            'currency_id': self.other_currency.id,
        })
        self.pos_config.write({
            'pricelist_id': other_pricelist.id,
            'available_pricelist_ids': [(6, 0, other_pricelist.ids)],
        })
        self.pos_config.open_ui()
        current_session = self.pos_config.current_session_id

        order = self.PosOrder.create({
            'company_id': self.env.company.id,
            'session_id': current_session.id,
            'partner_id': self.partner1.id,
            'lines': [(0, 0, {
                'name': "OL/0001",
                'product_id': self.product1.id,
                'price_unit': 100,
                'discount': 0,
                'qty': 1,
                'tax_ids': [[6, False, []]],
                'price_subtotal': 100,
                'price_subtotal_incl': 100,
            })],
            'pricelist_id': self.pos_config.pricelist_id.id,
            'amount_paid': 100.0,
            'amount_total': 100.0,
            'amount_tax': 0.0,
            'amount_return': 0.0,
        })
        self.assertEqual(order.currency_id, self.other_currency)

        # pay the whole order with the customer account
        payment_context = {"active_ids": order.ids, "active_id": order.id}
        order_payment = self.PosMakePayment.with_context(**payment_context).create({
            'amount': 100.0,
            'payment_method_id': self.customer_account_payment_method.id
        })
        order_payment.with_context(**payment_context).check()

        # The session is still open: nothing is accounted yet, the due only comes
        # from the pay later payment, which is already in the PoS currency.
        self.assertEqual(self.partner1.total_due, 0.0)
        self.assertEqual(self.partner1.get_total_due(self.other_currency.id), 100.0)

        # Once the session is closed the due comes from accounting, in company
        # currency, and must be converted back to the PoS currency.
        current_session.action_pos_session_closing_control()
        self.partner1.invalidate_recordset(['total_due'])
        self.assertEqual(self.partner1.total_due, 200.0)
        self.assertEqual(self.partner1.get_total_due(self.other_currency.id), 100.0)

        # Both sources add up, each one in the PoS currency.
        self.pos_config.open_ui()
        new_session = self.pos_config.current_session_id
        new_order = self.PosOrder.create({
            'company_id': self.env.company.id,
            'session_id': new_session.id,
            'partner_id': self.partner1.id,
            'lines': [(0, 0, {
                'name': "OL/0002",
                'product_id': self.product1.id,
                'price_unit': 50,
                'discount': 0,
                'qty': 1,
                'tax_ids': [[6, False, []]],
                'price_subtotal': 50,
                'price_subtotal_incl': 50,
            })],
            'pricelist_id': self.pos_config.pricelist_id.id,
            'amount_paid': 50.0,
            'amount_total': 50.0,
            'amount_tax': 0.0,
            'amount_return': 0.0,
        })
        payment_context = {"active_ids": new_order.ids, "active_id": new_order.id}
        order_payment = self.PosMakePayment.with_context(**payment_context).create({
            'amount': 50.0,
            'payment_method_id': self.customer_account_payment_method.id
        })
        order_payment.with_context(**payment_context).check()
        self.assertEqual(self.partner1.get_total_due(self.other_currency.id), 150.0)

    def test_invoicing_after_closing_session_intermediary_account(self):
        """ Test that an invoice can be created after the session is closed """
        # create customer account payment method
        receivable_account = self.env.company.account_default_pos_receivable_account_id.copy()
        self.cash_payment_method.receivable_account_id = receivable_account

        self.product1 = self.env['product.product'].create({
            'name': 'Product A',
            'is_storable': True,
            'categ_id': self.env.ref('product.product_category_all').id,
        })
        self.partner1.write({'parent_id': self.env['res.partner'].create({'name': 'Parent'}).id})

        self.pos_config.open_ui()
        current_session = self.pos_config.current_session_id

        # create pos order
        order = self.PosOrder.create({
            'company_id': self.env.company.id,
            'session_id': current_session.id,
            'partner_id': self.partner1.id,
            'lines': [(0, 0, {
                'name': "OL/0001",
                'product_id': self.product1.id,
                'price_unit': 6,
                'discount': 0,
                'qty': 1,
                'tax_ids': [[6, False, []]],
                'price_subtotal': 6,
                'price_subtotal_incl': 6,
            })],
            'pricelist_id': self.pos_config.pricelist_id.id,
            'amount_paid': 6.0,
            'amount_total': 6.0,
            'amount_tax': 0.0,
            'amount_return': 0.0,
        })

        payment_context = {"active_ids": order.ids, "active_id": order.id}
        order_payment = self.PosMakePayment.with_context(**payment_context).create({
            'amount': 6.0,
            'payment_method_id': self.cash_payment_method.id
        })
        order_payment.with_context(**payment_context).check()

        # close session
        current_session.action_pos_session_closing_control()

        accounting_partner = self.env['res.partner']._find_accounting_partner(self.partner1)
        self.assertEqual(accounting_partner.total_due, 0.0)

        # create invoice
        order.action_pos_order_invoice()
        self.assertEqual(accounting_partner.total_due, 0.0)

        # get journal entry that does the reverse payment, it the ref must contains Reversal
        reverse_payment = self.env['account.move'].search([('ref', 'ilike', "Reversal")])
        original_payment = self.env['account.move'].search([('ref', '=', current_session.display_name)])
        original_customer_payment_entry = original_payment.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
        reverser_customer_payment_entry = reverse_payment.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
        # check that both use the same account
        self.assertEqual(original_customer_payment_entry.account_id, receivable_account)
        self.assertEqual(original_customer_payment_entry.account_id.id, reverser_customer_payment_entry.account_id.id)
        self.assertEqual(reverser_customer_payment_entry.partner_id, original_customer_payment_entry.partner_id)
        aml_receivable = self.env['account.move.line'].read_group([('account_type', '=', 'asset_receivable')], fields=['account_id'], groupby='matching_number')
        self.assertEqual(len(aml_receivable), 3)
        for aml_g in aml_receivable:
            self.assertEqual(aml_g['matching_number_count'], 2)
