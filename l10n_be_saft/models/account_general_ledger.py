from odoo import api, models, _
from odoo.tools import SQL

SAFT_JOURNAL_TYPE_MAP = {
    'sale': 'S',        # Sale
    'purchase': 'P',    # Purchase
    'cash': 'F',        # Financial
    'bank': 'F',
    'general': 'D',     # Divers
}


class GeneralLedgerCustomHandler(models.AbstractModel):
    _inherit = 'account.general.ledger.report.handler'

    def _custom_options_initializer(self, report, options, previous_options):
        super()._custom_options_initializer(report, options, previous_options)

        if self.env.company.account_fiscal_country_id.code == 'BE':
            options.setdefault('buttons', []).append({
                'name': _('SAF-T'),
                'sequence': 50,
                'action': 'export_file',
                'action_param': 'l10n_be_export_saft_to_xml',
                'file_export_type': _('XML'),
            })

    @api.model
    def l10n_be_export_saft_to_xml(self, options):
        report = self.env['account.report'].browse(options['report_id'])
        template_vals = self._l10n_be_saft_prepare_report_values(report, options)
        file_data = report._generate_file_data_with_error_check(
            options,
            self.env['ir.qweb']._render,
            {'values': template_vals, 'template': 'l10n_be_saft.saft_template', 'file_type': 'xml'},
            template_vals['errors'],
        )
        file_data['file_name'] = self._get_be_saft_file_name(
            template_vals['company'].company_registry,
            template_vals['date_from'],
            template_vals['date_to'],
        )
        return file_data

    @api.model
    def _l10n_be_saft_prepare_report_values(self, report, options):
        template_vals = self._saft_prepare_report_values(report, options)
        template_vals.update({
            'xmlns': "urn:StandardAuditFile-Taxation-Financial:BE",
            'file_version': '1.20',
            'accounting_basis': 'A',
        })
        if not template_vals['company'].company_registry:
            template_vals['errors']['missing_company_registry'] = {
                'message': _("The Company Registry (CBE Number) is not set. "
                             "It is required to generate a valid Belgian SAF-T filename."),
                'action_text': _("Set Company Registry"),
                'action': template_vals['company']._get_records_action(name=_("Missing company details.")),
            }

        # TaxTableEntry is not required for Belgian SAF-T as the tax data is available in the TaxInformation element.
        # See the accompanying document pg 20.
        template_vals.pop('tax_vals_list', None)

        for val in template_vals['journal_vals_list']:
            val['type'] = SAFT_JOURNAL_TYPE_MAP.get(val['type'], 'D')
        return template_vals

    @api.model
    def _saft_fill_report_tax_details_values(self, report, options, values):
        """
        Belgian SAF-T override: Generates 'TaxInformation' nodes based on Tax Grid Tags.

        Standard SAF-T:
        - One TaxInformation node per move line (usually merged).
        - TaxAmount = Theoretical calculated tax.

        Belgian SAF-T:
        - One TaxInformation node per tag found on the line.
        - TaxAmount = The balance of the line, signed for base lines, absolute for tax lines.
        - Expense Line (100.00, Tag 81) -> TaxAmount 100.00
        - VAT Line (21.00, Tag 59)      -> TaxAmount 21.00 (absolute)
        """
        # --------------------------------------------------------------------------
        # LOGIC SUMMARY
        # 1. Trigger: Every line with a Tax Grid Tag gets a <TaxInformation> node.
        # 2. TaxAmount (<Amount>):
        #    - Tax Lines (411/451): Always absolute (abs of balance).
        #    - Base Lines: Signed: balance * tag_sign * invert_sign, where
        #      tag_sign comes from the grid code prefix (+/-) and invert_sign
        #      from tax_tag_invert (encodes customer invoice vs vendor bill).
        # 3. TaxBase (<Base>):
        #    - Tax Lines (411/451): Use 'tax_base_amount' stored in DB.
        #    - Base Lines (Expense): Use abs of the line's own balance.
        # --------------------------------------------------------------------------
        if self.env.company.account_fiscal_country_id.code != 'BE':
            return super()._saft_fill_report_tax_details_values(report, options, values)
        query = report._get_report_query(options, 'strict_range')
        tax_def_name = self.env['account.tax']._field_to_sql('tax_def', 'name')
        tax_from_rel_name = self.env['account.tax']._field_to_sql('tax_from_rel', 'name')

        # First, we get the relevant lines' data.
        line_data_query = SQL('''
            SELECT account_move_line.id,
                   account_move_line.balance,
                   account_move_line.amount_currency,
                   account_move_line.currency_id,
                   account_move_line.tax_base_amount,  -- Base amount used only for tax lines.
                   account_move_line.tax_tag_invert,

                   -- For tax lines, tax_line_id is set and we can use it to fetch the tax.
                   -- For base lines, we use account_move_line_account_tax_rel to find the related tax.
                   COALESCE(tax_def.id, tax_from_rel.id) as tax_id,
                   COALESCE(%(tax_def_name)s, %(tax_from_rel_name)s) as tax_name,
                   COALESCE(tax_def.amount, tax_from_rel.amount) as tax_rate,
                   COALESCE(tax_def.amount_type, tax_from_rel.amount_type) as tax_type

              FROM %(table_references)s
                   -- Taxes linked with tax_line_id.
         LEFT JOIN account_tax tax_def ON tax_def.id = account_move_line.tax_line_id
                   -- Taxes linked with base lines.
                   -- Base lines should not have multiple percentage taxes. For fixed taxes (like Recupel),
                   -- they do not have grids, so we safely filter them out to prevent cardinality issues.
         LEFT JOIN (
                           SELECT rel.account_move_line_id, rel.account_tax_id
                             FROM account_move_line_account_tax_rel rel
                             JOIN account_tax t ON t.id = rel.account_tax_id
                            WHERE t.amount_type != 'fixed'
                   ) tax_rel
                ON tax_rel.account_move_line_id = account_move_line.id
         LEFT JOIN account_tax tax_from_rel
                ON tax_from_rel.id = tax_rel.account_tax_id

            WHERE %(search_condition)s
        ''',
            tax_def_name=tax_def_name,
            tax_from_rel_name=tax_from_rel_name,
            table_references=query.from_clause,
            search_condition=query.where_clause,
        )

        line_data_map = {row['id']: row for row in self.env.execute_query_dict(line_data_query)}

        # Second, we get the tags for each line.
        if line_data_map:
            tag_name = self.env['account.account.tag'].with_context(lang='en_US')._field_to_sql('tag', 'name')
            tax_tag_query = SQL("""
                SELECT tag_rel.account_move_line_id,
                       -- Keep a deterministic tag order to avoid flaky TaxInformation node ordering across setups.
                       ARRAY_AGG(%(tag_name)s ORDER BY tag_rel.account_account_tag_id) as grid_codes
                  FROM account_account_tag_account_move_line_rel tag_rel
                  JOIN account_account_tag tag
                    ON tag.id = tag_rel.account_account_tag_id
                 WHERE tag_rel.account_move_line_id IN %(line_ids)s
                   AND tag.country_id = %(country_id)s
                GROUP BY tag_rel.account_move_line_id
            """,
                tag_name=tag_name,
                line_ids=tuple(line_data_map),
                country_id=self.env.ref('base.be').id,
            )

            # Finally, we fill the tax details values. One list per tag per line.
            for res in self.env.execute_query_dict(tax_tag_query):
                line_id = res['account_move_line_id']
                if line_id not in values['tax_detail_per_line_map']:
                    continue

                data = line_data_map[line_id]
                line_vals = values['tax_detail_per_line_map'][line_id]

                is_tax_line = bool(data['tax_base_amount'])

                # One TaxInformation node per tag.
                for grid_code in res['grid_codes']:
                    if is_tax_line:
                        # Belgian SAF-T: tax line amounts are always absolute.
                        amount = abs(data['balance'])
                        amount_currency = abs(data['amount_currency'])
                        tax_base_amount = abs(data['tax_base_amount'])
                    else:
                        # For base lines the sign depends on three factors:
                        # the balance sign, the tag sign, and tax_tag_invert.
                        tag_sign = -1 if grid_code[:1] == '-' else 1
                        invert_sign = -1 if data['tax_tag_invert'] else 1
                        amount = data['balance'] * tag_sign * invert_sign
                        amount_currency = data['amount_currency'] * tag_sign * invert_sign
                        tax_base_amount = abs(data['balance'])

                    val = {
                        'tax_id': grid_code[1:],  # Strip the sign (+/-)
                        'tax_name': data['tax_name'],
                        'tax_amount': data['tax_rate'],
                        'tax_amount_type': data['tax_type'],
                        'tax_base_amount': tax_base_amount,
                        'amount': amount,
                        'amount_currency': amount_currency,
                        'currency_code': line_vals['currency_code'],
                        'currency_id': data['currency_id'],
                        'rate': line_vals['rate'],
                    }

                    line_vals['tax_detail_vals_list'].append(val)

    def _saft_get_account_type(self, account_type):
        # EXTENDS account_saft
        if self.env.company.account_fiscal_country_id.code != 'BE':
            return super()._saft_get_account_type(account_type)
        return "GL"

    def _get_be_saft_file_name(self, company_registry, start_date, end_date):
        """
        Returns the SAF-T file name according to the format defined in the Belgian SAF-T standard:
        BE-SAF-T_<BE_CBE_Number>_<StartDate>_<EndDate>_<Seq of the file>_<Total number of files>.xml

        Sequence of the file and the total number of files are defaulted as 1 and 1 as we generate only one file.
        """
        return f"BE-SAF-T_BE{company_registry}_{start_date.replace('-', '')}_{end_date.replace('-', '')}_1_1.xml"
