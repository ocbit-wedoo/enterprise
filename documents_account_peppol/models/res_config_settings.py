from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    documents_account_peppol_folder_id = fields.Many2one(
        related='company_id.documents_account_peppol_folder_id',
        readonly=False
    )
    documents_account_peppol_tag_ids = fields.Many2many(
        related='company_id.documents_account_peppol_tag_ids',
        readonly=False
    )

    @api.depends('documents_account_peppol_folder_id')
    def _compute_peppol_purchase_journal_required(self):
        # EXTENDS account_peppol
        super()._compute_peppol_purchase_journal_required()
        for config in self:
            allowed = config.company_id._peppol_allows_document_reception()
            if config.documents_account_peppol_folder_id and allowed:
                config.peppol_purchase_journal_required = False
