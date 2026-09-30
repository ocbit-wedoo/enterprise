from odoo import api, models


class L10nKeOSCUCode(models.Model):
    _inherit = 'l10n_ke_edi_oscu.code'

    def _load_pos_data(self, data):
        domain = self._load_pos_data_domain(data)
        fields = self._load_pos_data_fields(data['pos.config']['data'][0]['id'])
        data = self.search_read(domain, fields, load=False)
        return {
            'data': data,
            'fields': fields,
        }

    @api.model
    def _load_pos_data_fields(self, config_id):
        return ['code_type']

    @api.model
    def _load_pos_data_domain(self, data):
        products = data['product.product']['data']
        code_ids = [product['l10n_ke_packaging_unit_id'] for product in products if product.get('l10n_ke_packaging_unit_id')]
        return [('id', 'in', code_ids)]
