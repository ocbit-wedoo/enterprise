from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Create the Tax Provision Account (account.account) for BE companies
    code = 'a4118'
    digits = env['account.chart.template']._get_be_template_data().get('code_digits', 6)

    for company in env['res.company'].search([('chart_template', 'like', 'be_%')], order='parent_path'):
        ChartTemplate = env['account.chart.template'].with_company(company)
        if (
            not ChartTemplate.ref(code, raise_if_not_found=False)
            and (account := ChartTemplate._get_account_account(company.chart_template).get(code))
        ):
            account['code'] = f'{account["code"]:<0{digits}}'
            ChartTemplate._load_data({'account.account': {code: account}})
