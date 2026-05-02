# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""
CRUD helpers for bundled Server Scripts — mirrors the workflow.py pattern.
JSON files live alongside this module; the setup layer and patches call
create_server_script / delete_server_script with the loaded dict.
"""

import frappe
from frappe_agile.frappe_agile.custom.workflow.workflow import get_json_file


def get_server_script_json_file(file_name: str) -> dict:
	"""Load a Server Script JSON from the custom/server_script folder."""
	folder = frappe.get_app_path("frappe_agile", "frappe_agile", "custom", "server_script")
	return get_json_file(file_name, folder)


def create_server_script(definition: dict):
	"""
	Create or update a Server Script from a JSON definition dict.

	Args:
		definition (dict): Must contain at least ``name`` and ``script_type``.
	"""
	if not isinstance(definition, dict) or not definition.get("name"):
		frappe.log_error(title="Invalid Server Script definition — missing 'name'.")
		return

	name = definition["name"]

	try:
		if not frappe.db.exists("Server Script", name):
			frappe.get_doc(definition).insert(ignore_permissions=True)
		else:
			doc = frappe.get_doc("Server Script", name)
			doc.update(definition)
			doc.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="Server Script Creation Error",
			message=f"Failed to create/update Server Script '{name}':\n{frappe.get_traceback()}"
		)


def delete_server_script(definition: dict):
	"""
	Delete a Server Script by its name key.

	Args:
		definition (dict): Must contain ``name``.
	"""
	name = definition.get("name")
	if not name:
		frappe.log_error(title="Missing 'name' in Server Script deletion input.")
		return

	try:
		if frappe.db.exists("Server Script", name):
			frappe.delete_doc("Server Script", name, ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="Server Script Deletion Error",
			message=f"Failed to delete Server Script '{name}':\n{frappe.get_traceback()}"
		)
