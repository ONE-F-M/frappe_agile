# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""Delete the Find PR On GitHub Server Script from sites that created it."""

from frappe_agile.frappe_agile.custom.server_script.server_script import delete_server_script


def execute():
	delete_server_script({"name": "Find PR On GitHub"})
