# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""
Setup functions for Assignment Rules — called from after_install and after_migrate.
"""

from frappe_agile.frappe_agile.custom.assignment_rule.assignment_rule import (
	get_assignment_rule_json_file,
	create_assignment_rule,
	delete_assignment_rule,
)


def create_assignment_rules():
	"""Create or update all bundled Assignment Rules."""
	create_assignment_rule(get_assignment_rule_json_file("work_item_developer.json"))
	create_assignment_rule(get_assignment_rule_json_file("work_item_process_owner.json"))
	create_assignment_rule(get_assignment_rule_json_file("work_item_pr_reviewer.json"))


def delete_assignment_rules():
	"""Delete all bundled Assignment Rules (used on uninstall)."""
	delete_assignment_rule(get_assignment_rule_json_file("work_item_developer.json"))
	delete_assignment_rule(get_assignment_rule_json_file("work_item_process_owner.json"))
	delete_assignment_rule(get_assignment_rule_json_file("work_item_pr_reviewer.json"))
