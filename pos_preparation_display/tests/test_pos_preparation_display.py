# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import timedelta

from odoo.addons.point_of_sale.tests.common import TestPoSCommon
from odoo.tests import tagged
from odoo import Command, fields


@tagged('post_install', '-at_install')
class TestPosPreparationDisplay(TestPoSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config

    def test_load_preparation_display_model(self):
        
        config1 = self.env['pos.config'].create({
            'name': 'rest1',
            'active': False
        })
        config2 = self.env['pos.config'].create({
            'name': 'rest2'
        })
        config3 = self.env['pos.config'].create({
            'name': 'rest3'
        })
        config4 = self.env['pos.config'].create({
            'name': 'rest4'
        })
        
        #pos preperation display linked to specific configs
        display1 = self.env['pos_preparation_display.display'].create({
            'name': 'Preparation Display 1',
            'pos_config_ids': [Command.link(config1.id)]
        })
        display2 = self.env['pos_preparation_display.display'].create({
            'name': 'Preparation Display 2',
            'pos_config_ids': [Command.link(config2.id)]
        })
        display3 = self.env['pos_preparation_display.display'].create({
            'name': 'Preparation Display 3',
            'pos_config_ids': []
        })
        display4 = self.env['pos_preparation_display.display'].create({
            'name': 'Preparation Display 4',
            'pos_config_ids': [Command.link(config3.id)]
        })
        
        config2.open_ui()
        config3.open_ui()
        config4.open_ui()
        
        self.assertEqual({d['id'] for d in config2.current_session_id.load_data([])['pos_preparation_display.display']['data']},
                         {display1.id, display2.id, display3.id})
        self.assertEqual({d['id'] for d in config3.current_session_id.load_data([])['pos_preparation_display.display']['data']},
                         {display1.id, display3.id, display4.id})
        self.assertEqual({d['id'] for d in config4.current_session_id.load_data([])['pos_preparation_display.display']['data']},
                         {display1.id, display3.id})

    def _setup_display_with_order(self):
        """Open a session, sync one paid order and return (display, pdis_order)."""
        pos_categ = self.env['pos.category'].create({'name': 'Kitchen'})
        product = self.create_product('Burger', self.categ_basic, 10.0)
        product.pos_categ_ids = [Command.set(pos_categ.ids)]

        display = self.env['pos_preparation_display.display'].create({
            'name': 'Kitchen Display',
            'pos_config_ids': [Command.link(self.config.id)],
            'category_ids': [Command.link(pos_categ.id)],
        })

        self.open_new_session()
        self.env['pos.order'].sync_from_ui([self.create_ui_order_data([(product, 1)])])

        pdis_order = self.env['pos_preparation_display.order'].search([
            ('pos_order_id.session_id', '=', self.pos_session.id),
        ])
        self.assertEqual(len(pdis_order), 1, "the synced order reached the preparation display")

        return display, pdis_order

    def _screen_order_count(self, display):
        return len(display.get_preparation_display_data()['orders'])

    def test_stageless_orders_filter_by_display_config(self):
        display = self.env['pos_preparation_display.display'].create({
            'name': 'Kitchen Display',
            'pos_config_ids': [Command.link(self.config.id)],
        })
        self.open_new_session()
        matching_pos_order = self.env['pos.order'].create({
            'name': 'Matching POS order',
            'session_id': self.pos_session.id,
            'config_id': self.config.id,
            'amount_tax': 0,
            'amount_total': 0,
            'amount_paid': 0,
            'amount_return': 0,
        })
        matching_order = self.env['pos_preparation_display.order'].create({
            'pos_order_id': matching_pos_order.id,
        })
        other_config = self.config.copy({'name': 'Other POS'})
        other_config.open_ui()
        other_order = self.env['pos.order'].create({
            'name': 'Other POS order',
            'session_id': other_config.current_session_id.id,
            'amount_tax': 0,
            'amount_total': 0,
            'amount_paid': 0,
            'amount_return': 0,
        })
        self.env['pos_preparation_display.order'].create({
            'pos_order_id': other_order.id,
        })
        unlinked_order = self.env['pos_preparation_display.order'].create({})

        stageless_orders = display._get_stageless_orders_in_display()
        self.assertEqual(
            set(stageless_orders.ids),
            set((matching_order | unlinked_order).ids),
            "only unlinked orders and orders from the display's POS config are stageless",
        )

    def _badge_order_count(self, display):
        # order_count does not depend on the order records, invalidate manually
        display.invalidate_recordset(['order_count'])
        return display.order_count

    def test_order_count_includes_orders_older_than_today(self):
        """An order that crossed midnight while still open must stay counted in
        the kanban badge for as long as the preparation screen shows it."""
        display, pdis_order = self._setup_display_with_order()

        self.assertEqual(self._screen_order_count(display), 1)
        self.assertEqual(self._badge_order_count(display), 1)

        # the session stays open past midnight
        self.env.cr.execute(
            "UPDATE pos_preparation_display_order SET create_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(days=1), pdis_order.id),
        )
        pdis_order.invalidate_recordset(['create_date'])

        self.assertEqual(self._screen_order_count(display), 1,
                         "the order is still displayed on the preparation screen")
        self.assertEqual(self._badge_order_count(display), 1,
                         "an order still shown on the screen must still be counted in the badge")

    def test_order_count_cleared_by_reset(self):
        """Resetting the display clears the screen, so it must clear the badge too."""
        display, _pdis_order = self._setup_display_with_order()

        self.assertEqual(self._screen_order_count(display), 1)
        self.assertEqual(self._badge_order_count(display), 1)

        display.reset()

        self.assertEqual(self._screen_order_count(display), 0,
                         "reset removes the order from the preparation screen")
        self.assertEqual(self._badge_order_count(display), 0,
                         "reset must leave no outstanding work in the badge either")
