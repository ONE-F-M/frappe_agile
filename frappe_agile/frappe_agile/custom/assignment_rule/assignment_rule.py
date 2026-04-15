# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""
Helpers for creating / deleting Assignment Rules from JSON config files.

Mirrors the pattern used by ``frappe_agile.frappe_agile.custom.workflow.workflow``
for Workflows — load a JSON definition, upsert into the database, and clean up
on uninstall.
"""

import json
import os

import frappe


def get_assignment_rule_json_file(file_name: str) -> dict:
	"""Load an Assignment Rule JSON definition from this folder."""
	folder = os.path.dirname(os.path.abspath(__file__))
	file_path = os.path.join(folder, file_name)

	if not os.path.isfile(file_path):
		frappe.log_error(
			title="Assignment Rule – file not found",
			message=f"Expected assignment rule config at: {file_path}",
		)
		return {}

	try:
		with open(file_path, "r") as f:
			return json.load(f)
	except json.JSONDecodeError as e:
		frappe.log_error(
			title=f"Assignment Rule – invalid JSON in {file_name}",
			message=str(e),
		)
	return {}


def create_assignment_rule(rule_config: dict):
	"""
	Create or update an Assignment Rule from a JSON config dictionary.

	If the rule already exists (matched by ``name``), it is updated in place.
	Otherwise a new Assignment Rule document is inserted.
	"""
	if not rule_config or "name" not in rule_config:
		return

	rule_name = rule_config["name"]

	try:
		if frappe.db.exists("Assignment Rule", rule_name):
			doc = frappe.get_doc("Assignment Rule", rule_name)
			doc.update(rule_config)
			doc.save(ignore_permissions=True)
		else:
			doc = frappe.get_doc(rule_config)
			doc.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title=f"Assignment Rule – failed to create/update '{rule_name}'",
			message=frappe.get_traceback(),
		)


def delete_assignment_rule(rule_config: dict):
	"""Delete an Assignment Rule by name if it exists."""
	rule_name = rule_config.get("name")
	if not rule_name:
		return

	try:
		if frappe.db.exists("Assignment Rule", rule_name):
			frappe.delete_doc("Assignment Rule", rule_name, ignore_permissions=True, force=True)
	except Exception:
		frappe.log_error(
			title=f"Assignment Rule – failed to delete '{rule_name}'",
			message=frappe.get_traceback(),
		)
