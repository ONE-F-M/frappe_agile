# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""Create the Find PR On GitHub Server Script on sites that already have the others."""

from frappe_agile.frappe_agile.custom.server_script.server_script import (
	create_server_script,
	get_server_script_json_file,
)


def execute():
	create_server_script(get_server_script_json_file("find_pr_on_github.json"))
