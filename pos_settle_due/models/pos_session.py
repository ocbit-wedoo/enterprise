from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _reconcile_account_move_lines(self, data):
        data = super()._reconcile_account_move_lines(data)
        pay_later_move_lines = data.get('pay_later_move_lines')
        # Reconcile customer receivable move lines
        if not pay_later_move_lines:
            return data
        for (partner, account, currency), lines in pay_later_move_lines.grouped(
            lambda line: (line.partner_id, line.account_id, line.currency_id)
        ).items():
            if not partner:
                continue
            domain = [
                "|",
                ("journal_id", "=", self.config_id.journal_id.id),
                "&",
                ("move_type", "=", "out_invoice"),
                ("move_id.pos_order_ids", "!=", False),
                ("account_id", "=", account.id),
                ("partner_id", "=", partner.id),
                ("currency_id", "=", currency.id),
                ("reconciled", "=", False),
                ("parent_state", "=", "posted"),
            ]
            # Only credits can be allocated: without any there is nothing to
            # reconcile, and no reason to load the customer's open items (a
            # customer buying on credit for years has tens of thousands).
            lines |= lines.search(domain + [("amount_residual_currency", "<", 0)], order="date, id", limit=2000)
            to_allocate = -sum(
                residual for residual in lines.mapped("amount_residual_currency") if residual < 0
            )
            if currency.is_zero(to_allocate):
                continue
            # Open items in the order the reconciliation consumes them (see
            # _optimize_reconciliation_plan), and only as many as the credits
            # cover: it would leave the following ones untouched anyway.
            covered = 0.0
            candidates = lines.search(
                domain + [("amount_residual_currency", ">", 0)],
                order="date, id",
                limit=2000,
            ).sorted(lambda line: (line.date_maturity or line.date, line.amount_currency, line.balance))
            for candidate in candidates:
                if currency.compare_amounts(covered, to_allocate) >= 0:
                    break
                lines |= candidate
                covered += candidate.amount_residual_currency
            self.env["account.move.line"]._reconcile_plan([lines])
        return data
