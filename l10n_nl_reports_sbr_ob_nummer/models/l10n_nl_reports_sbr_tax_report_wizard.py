from odoo import models

class L10nNlTaxReportSBRWizard(models.TransientModel):
    _inherit = 'l10n_nl_reports_sbr.tax.report.wizard'

    def _get_sbr_identifier(self, options=None):
        is_company_only = not options or options.get('tax_unit', 'company_only') == 'company_only'
        if is_company_only and self.env.company.l10n_nl_reports_sbr_ob_nummer:
            return self.env.company.l10n_nl_reports_sbr_ob_nummer
        return super()._get_sbr_identifier(options)
