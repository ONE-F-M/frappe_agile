# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""
Patch: Create bundled Server Scripts for existing installations.
Fresh installs receive them via after_install; this patch covers upgrades.
"""

import frappe
from frappe_agile.setup.server_script import create_server_scripts


def execute():
	create_server_scripts()
	frappe.db.commit()
