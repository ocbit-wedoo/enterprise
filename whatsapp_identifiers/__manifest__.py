{
    'name': 'WhatsApp Identifiers',
    'category': 'Marketing/WhatsApp',
    'summary': 'Mandatory Support for WhatsApp Business-Scoped User IDs (BSUID)',
    'version': '1.0',
    'description': (
        'Retroactively add support for Business-Scoped User IDs added to Whatsapp in June 2026 as part of the username update. '
        'These allow users to contact your business without sharing their phone number.\n\n'
        'This module MUST be installed to be able to reply to incoming messages.'
    ),
    'depends': ['whatsapp'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'auto_install': True,
    'license': 'OEEL-1',
}
