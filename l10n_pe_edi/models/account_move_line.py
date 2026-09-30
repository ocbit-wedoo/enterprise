# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.tools.sql import column_exists, create_column

from .account_tax import CATALOG07


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    l10n_pe_edi_allowance_charge_reason_code = fields.Selection(
        selection=[
            ('00', 'Discounts affecting the IGV/IVAP taxable base'),
            ('01', 'Discounts not affecting the IGV/IVAP taxable base'),
            ('02', 'Global discounts affecting the IGV/IVAP taxable base'),
            ('03', 'Global discounts not affecting the IGV/IVAP taxable base'),
            ('04', 'Global discounts for taxed advance payments affecting the IGV/IVAP taxable base'),
            ('05', 'Global discounts for exonerated advance payments'),
            ('06', 'Global discounts for unaffected advance payments'),
            ('07', 'Compensation factor - Emergency Decree No. 010-2004'),
            ('20', 'ISC advance payment'),
            ('45', 'FISE'),
            ('46', 'Consumption surcharge and/or tips'),
            ('47', 'Charges affecting the IGV/IVAP taxable base'),
            ('48', 'Charges not affecting the IGV/IVAP taxable base'),
            ('49', 'Global charges affecting the IGV/IVAP taxable base'),
            ('50', 'Global charges not affecting the IGV/IVAP taxable base'),
            ('51', 'Perceptions of Internal Sales'),
            ('52', 'Perception to the Acquisition of Fuel'),
            ('53', 'Perception done to the Agent of Perception with Special Rate'),
            ('54', 'Contribution factor - Emergency Decree No. 010-2004'),
            ('55', 'Other Charges no Related to the Service (Obsolete)'),
            ('61', 'Income tax withholding for advance payments'),
            ('62', 'IGV withholding'),
            ('63', 'Second category income tax withholding'),
        ],
        string="Allowance or Charge reason",
        default=False,
        help="Catalog 53 of possible reasons of discounts")
    l10n_pe_edi_affectation_reason = fields.Selection(
        selection=CATALOG07,
        string="EDI Affect. Reason",
        store=True, readonly=False, compute='_compute_l10n_pe_edi_affectation_reason',
        help="Type of Affectation to the IGV, Catalog No. 07")

    def _auto_init(self):
        cr = self.env.cr

        # Skip the computation of the field `l10n_pe_edi_affectation_reason` at the module installation
        if not column_exists(cr, "account_move_line", "l10n_pe_edi_affectation_reason"):
            create_column(cr, "account_move_line", "l10n_pe_edi_affectation_reason", "varchar")

        return super()._auto_init()

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends('tax_ids', 'price_unit')
    def _compute_l10n_pe_edi_affectation_reason(self):
        '''Indicates how the IGV affects the invoice line product it represents the Catalog No. 07 of SUNAT.
        NOTE: Not all the cases are supported for the moment, in the future we might add this as field in a special
        tab for this rare configurations.
        '''
        for line in self:
            taxes_with_code = line.tax_ids.filtered(lambda tax: tax.l10n_pe_edi_tax_code)
            if not taxes_with_code or line.display_type in ('tax', 'payment_term'):
                line.l10n_pe_edi_affectation_reason = False
            else:
                line.l10n_pe_edi_affectation_reason = taxes_with_code[0].l10n_pe_edi_affectation_reason
