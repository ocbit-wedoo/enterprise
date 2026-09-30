# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import fields, models
from odoo.tools import SQL, Query


class BudgetReport(models.Model):
    _name = 'budget.report'
    _inherit = 'analytic.plan.fields.mixin'
    _description = "Budget Report"
    _auto = False
    _order = False

    date = fields.Date('Date')
    res_model = fields.Char('Model', readonly=True)
    res_id = fields.Many2oneReference('Document', model_field='res_model', readonly=True)
    description = fields.Char('Description', readonly=True)
    company_id = fields.Many2one('res.company', 'Company', readonly=True)
    user_id = fields.Many2one('res.users', 'User', readonly=True)
    line_type = fields.Selection([('budget', 'Budget'), ('committed', 'Committed'), ('achieved', 'Achieved')], 'Type', readonly=True)
    budget = fields.Float('Budget', readonly=True)
    committed = fields.Float('Committed', readonly=True)
    achieved = fields.Float('Achieved', readonly=True)
    budget_analytic_id = fields.Many2one('budget.analytic', 'Budget Analytic', readonly=True)
    budget_line_id = fields.Many2one('budget.line', 'Budget Line', readonly=True)

    def _shape_join(self, model1, alias1, model2, alias2, shape):
        plan_fnames = self._get_plan_fnames()
        return SQL(' AND ').join([
            SQL(
                "%(model1)s = %(model2)s",
                model1=self.env[model1]._field_to_sql(alias1, fname),
                model2=self.env[model2]._field_to_sql(alias2, fname),
            )
            for fname, is_set in zip(plan_fnames, shape)
            if is_set
        ]) or SQL('TRUE')

    def _get_bl_query(self, plan_fnames):
        budget_line_ids = self.env.context.get('budget_report_budget_line_ids')
        return SQL(
            """
            SELECT CONCAT('bl', bl.id::TEXT) AS id,
                   bl.budget_analytic_id AS budget_analytic_id,
                   bl.id AS budget_line_id,
                   'budget.analytic' AS res_model,
                   bl.budget_analytic_id AS res_id,
                   bl.date_from AS date,
                   ba.name AS description,
                   bl.company_id AS company_id,
                   NULL AS user_id,
                   'budget' AS line_type,
                   bl.budget_amount AS budget,
                   0 AS committed,
                   0 AS achieved,
                   %(plan_fields)s
              FROM budget_line bl
              JOIN budget_analytic ba ON ba.id = bl.budget_analytic_id
              %(budget_line_ids_condition)s
            """,
            plan_fields=SQL(', ').join(self.env['budget.line']._field_to_sql('bl', fname) for fname in plan_fnames),
            budget_line_ids_condition=SQL('WHERE bl.id = ANY(%(budget_line_ids)s)', budget_line_ids=budget_line_ids) if budget_line_ids else SQL(''),
        )

    def _get_aal_query(self, plan_fnames):
        def get_query(bl_join, bl_condition):
            query = Query(self.env, alias='aal', table=SQL.identifier('account_analytic_line'))
            query.add_join(bl_join, 'bl', 'budget_line', bl_condition)
            query.add_join('LEFT JOIN', 'ba', 'budget_analytic', SQL("ba.id = bl.budget_analytic_id"))
            return query

        budget_line_ids = self.env.context.get('budget_report_budget_line_ids')

        # For performance reasons, we split the query into 3 parts and then UNION ALL the results
        # (faster than doing a single query with an OR on the left join condition):
        # Q1 - analytic lines with no matching budget line at all.
        # Q2 - analytic lines matched to a null-company budget line.
        # Q3 - analytic lines matched to a company-specific budget line.

        select_columns = [
            "CONCAT('aal', aal.id::TEXT) AS id",
            "bl.budget_analytic_id AS budget_analytic_id",
            "bl.id AS budget_line_id",
            "'account.analytic.line' AS res_model",
            "aal.id AS res_id",
            "aal.date AS date",
            "aal.name AS description",
            "aal.company_id AS company_id",
            "aal.user_id AS user_id",
            "'achieved' AS line_type",
            "0 AS budget",
            "aal.amount * CASE WHEN ba.budget_type = 'expense' THEN -1 ELSE 1 END AS committed",
            "aal.amount * CASE WHEN ba.budget_type = 'expense' THEN -1 ELSE 1 END AS achieved",
            *(self.env['account.analytic.line']._field_to_sql('aal', fname) for fname in plan_fnames),
        ]

        def where_account_type(query):
            query.add_join('LEFT JOIN', 'aa', 'account_account', SQL("aa.id = aal.general_account_id"))
            return SQL(
                """
                (
                    SPLIT_PART(aa.account_type, '_', 1) IN ('income', 'expense')
                    OR aa.account_type IN ('asset_current', 'asset_non_current', 'asset_fixed')
                    OR aa.account_type IS NULL
                )
                """
            )

        bl_domain = [('id', 'in', budget_line_ids)] if budget_line_ids else []
        budget_lines = self.env['budget.line'].sudo().search(bl_domain)

        # Group budget lines by the shape of their plan fields to optimize the query
        # For each budget line, we only care which fields are set, not their specific values.
        shape2budget_lines = budget_lines._by_shape()

        queries = []

        # Q1 - analytic lines with no matching budget line at all.
        if not budget_line_ids:
            query = get_query('LEFT JOIN', SQL("FALSE"))
            # filter it so that we only get the aals that have no bl
            if shape2budget_lines:
                query.add_where(SQL(
                    "NOT EXISTS (SELECT 1 FROM (%(union)s) matched_aal WHERE matched_aal.id = aal.id)",
                    union=SQL(' UNION ALL ').join([
                        get_query('JOIN', SQL(
                            """
                                aal.date >= bl.date_from
                                AND aal.date <= bl.date_to
                                AND bl.id = ANY(%(ids)s)
                                AND %(shape_join)s
                            """,
                            ids=line_ids.ids,
                            shape_join=self._shape_join('account.analytic.line', 'aal', 'budget.line', 'bl', shape),
                        )).select("DISTINCT aal.id")
                        for shape, line_ids in shape2budget_lines.items()
                    ])
                ))
            query.add_where(where_account_type(query))
            queries.append(query.select(*select_columns))

        # Q2 - analytic lines matched to a null-company budget line.
        # Q3 - analytic lines matched to a company-specific budget line.
        company_conditions = [
            SQL('bl.company_id IS NULL'),
            SQL('aal.company_id = bl.company_id'),
        ]

        for company_condition in company_conditions:
            for shape, line_ids in shape2budget_lines.items():
                query = get_query('JOIN', SQL(
                    """
                        %(company_condition)s
                        AND aal.date >= bl.date_from
                        AND aal.date <= bl.date_to
                        AND bl.id = ANY(%(ids)s)
                        AND %(shape_join)s
                    """,
                    company_condition=company_condition,
                    ids=line_ids.ids,
                    shape_join=self._shape_join('account.analytic.line', 'aal', 'budget.line', 'bl', shape),
                ))
                query.add_where(SQL(
                    """CASE
                        WHEN ba.budget_type = 'expense' THEN ((%(profitability)s) = 'loss')
                        WHEN ba.budget_type = 'revenue' THEN ((%(profitability)s) = 'revenue')
                        ELSE TRUE
                    END""",
                    profitability=self.env['account.analytic.line']._field_to_sql('aal', 'analytic_profitability', query),
                ))
                query.add_where(where_account_type(query))
                queries.append(query.select(*select_columns))

        return SQL(' UNION ALL ').join(queries)

    def _get_pol_query(self, plan_fnames):
        budget_line_ids = self.env.context.get('budget_report_budget_line_ids')
        qty_invoiced_table = SQL(
            """
               SELECT SUM(
                          CASE WHEN COALESCE(uom_aml.id != uom_pol.id, FALSE)
                               THEN ROUND((aml.quantity / uom_aml.factor) * uom_pol.factor, -LOG(uom_pol.rounding)::integer)
                               ELSE COALESCE(aml.quantity, 0)
                          END
                          * CASE WHEN am.move_type = 'in_invoice' THEN 1
                                 WHEN am.move_type = 'in_refund' THEN -1
                                 ELSE 0 END
                      ) AS qty_invoiced,
                      pol.id AS pol_id
                 FROM purchase_order po
            LEFT JOIN purchase_order_line pol ON pol.order_id = po.id
            LEFT JOIN account_move_line aml ON aml.purchase_line_id = pol.id
            LEFT JOIN account_move am ON aml.move_id = am.id
            LEFT JOIN uom_uom uom_aml ON uom_aml.id = aml.product_uom_id
            LEFT JOIN uom_uom uom_pol ON uom_pol.id = pol.product_uom
            LEFT JOIN uom_category uom_category_aml ON uom_category_aml.id = uom_pol.category_id
            LEFT JOIN uom_category uom_category_pol ON uom_category_pol.id = uom_pol.category_id
                WHERE aml.parent_state = 'posted'
             GROUP BY pol.id
        """)

        def get_query(bl_join, bl_condition):
            query = Query(self.env, alias='pol', table=SQL.identifier('purchase_order_line'))
            query.add_join('LEFT JOIN', 'qty_invoiced_table', SQL("(%s)", qty_invoiced_table), SQL("qty_invoiced_table.pol_id = pol.id"))
            query.add_join('JOIN', 'po', 'purchase_order', SQL("pol.order_id = po.id AND po.state in ('purchase', 'done')"))
            query.add_join('JOIN', 'a', SQL(
                """
                LATERAL (
                    SELECT rate, %(analytic_columns)s
                      FROM JSONB_TO_RECORDSET(pol.analytic_json) AS x(rate FLOAT, %(field_cast)s)
                )
                """,
                analytic_columns=SQL(', ').join(SQL.identifier(fname) for fname in plan_fnames),
                field_cast=SQL(', ').join(SQL('%s FLOAT', SQL.identifier(fname)) for fname in plan_fnames),
            ), SQL("TRUE"))
            query.add_join(bl_join, 'bl', 'budget_line', bl_condition)
            query.add_join('LEFT JOIN', 'ba', 'budget_analytic', SQL("ba.id = bl.budget_analytic_id"))
            return query

        select_columns = [
            "(pol.id::TEXT || '-' || ROW_NUMBER() OVER (PARTITION BY pol.id ORDER BY pol.id)) AS id",
            "bl.budget_analytic_id AS budget_analytic_id",
            "bl.id AS budget_line_id",
            "'purchase.order' AS res_model",
            "po.id AS res_id",
            "po.date_order AS date",
            "pol.name AS description",
            "pol.company_id AS company_id",
            "po.user_id AS user_id",
            "'committed' AS line_type",
            "0 AS budget",
            """
                COALESCE(pol.price_subtotal::FLOAT, pol.price_unit::FLOAT * pol.product_qty)
                     / COALESCE(NULLIF(pol.product_qty, 0), 1)
                     * (pol.product_qty - COALESCE(qty_invoiced_table.qty_invoiced, 0))
                     / po.currency_rate
                     * (a.rate)
                     * CASE WHEN ba.budget_type = 'both' THEN -1 ELSE 1 END AS committed
            """,
            "0 AS achieved",
            *(self.env['account.analytic.line']._field_to_sql('a', fname) for fname in plan_fnames),
        ]

        bl_domain = [('id', 'in', budget_line_ids)] if budget_line_ids else []
        budget_lines = self.env['budget.line'].sudo().search(bl_domain)
        shape2budget_lines = budget_lines._by_shape()

        # Q1 - PO lines matched to a null-company budget line.
        # Q2 - PO lines matched to a company-specific budget line.
        company_conditions = [
            SQL('bl.company_id IS NULL'),
            SQL('po.company_id = bl.company_id'),
        ]

        queries = []
        for company_condition in company_conditions:
            for shape, line_ids in shape2budget_lines.items():
                query = get_query('JOIN', SQL(
                    """
                        %(company_condition)s
                        AND po.date_order >= bl.date_from
                        AND date_trunc('day', po.date_order) <= bl.date_to
                        AND bl.id = ANY(%(ids)s)
                        AND %(shape_join)s
                    """,
                    company_condition=company_condition,
                    ids=line_ids.ids,
                    shape_join=self._shape_join('budget.line', 'a', 'budget.line', 'bl', shape),
                ))
                query.add_where(SQL("pol.product_qty > COALESCE(qty_invoiced_table.qty_invoiced, 0)"))
                query.add_where(SQL("ba.budget_type != 'revenue'"))
                queries.append(query.select(*select_columns))

        return SQL(' UNION ALL ').join(queries)

    @property
    def _table_query(self):
        self.env['account.move.line'].flush_model()
        self.env['budget.line'].flush_model()
        self.env['account.analytic.line'].flush_model()
        self.env['purchase.order'].flush_model()
        self.env['purchase.order.line'].flush_model()
        project_plan, other_plans = self.env['account.analytic.plan']._get_all_plans()
        plan_fnames = [
            fname
            for plan in project_plan | other_plans
            if (fname := plan._column_name()) in self
        ]
        return SQL(" UNION ALL ").join(filter(None, (
            self._get_bl_query(plan_fnames),
            self._get_aal_query(plan_fnames),
            self._get_pol_query(plan_fnames),
        )))

    def action_open_reference(self):
        self.ensure_one()
        if self.res_model == 'account.analytic.line':
            analytical_line = self.env['account.analytic.line'].browse(self.res_id)
            if analytical_line.move_line_id:
                return analytical_line.move_line_id.action_open_business_doc()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'view_mode': 'form',
            'res_id': self.res_id,
        }
