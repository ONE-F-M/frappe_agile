import json
import frappe
from frappe_agile.setup.workflow import create_workflows, delete_workflows


REQUIRED_ROLES = ["Business Analyst", "Developer", "Process Owner"]

# ---------------------------------------------------------------------------
# Backlog List Filter
# ---------------------------------------------------------------------------
_BACKLOG_FILTER_NAME = "Backlog"
_BACKLOG_FILTER_DOCTYPE = "Work Item"


def create_roles():
	for role_name in REQUIRED_ROLES:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(ignore_permissions=True)


def get_backlog_filters_json() -> str:
	"""Generate the filters JSON for the Backlog saved filter."""
	filters = [
		["Work Item", "workflow_state", "!=", "Done", False]
	]
	
	active_sprints = frappe.get_all("Sprint", filters={"status": "Active"}, pluck="name")
	if active_sprints:
		filters.append(["Work Item", "sprint", "not in", active_sprints, False])
		
	return json.dumps(filters)


def create_backlog_list_filter():
	"""Create the shared 'Backlog' List Filter for Work Item if it doesn't exist."""
	existing = frappe.db.get_value(
		"List Filter",
		{
			"filter_name": _BACKLOG_FILTER_NAME,
			"reference_doctype": _BACKLOG_FILTER_DOCTYPE,
			"for_user": "",
		},
	)
	if existing:
		return

	frappe.get_doc(
		{
			"doctype": "List Filter",
			"filter_name": _BACKLOG_FILTER_NAME,
			"reference_doctype": _BACKLOG_FILTER_DOCTYPE,
			"for_user": "",
			"filters": get_backlog_filters_json(),
		}
	).insert(ignore_permissions=True)


def update_backlog_list_filter(doc=None, method=None):
	"""
	Update the shared Backlog List Filter's filters JSON.
	Hooked to Sprint on_update / on_trash to ensure 'not in active sprint' stays accurate.
	"""
	filter_name = frappe.db.get_value(
		"List Filter",
		{
			"filter_name": _BACKLOG_FILTER_NAME,
			"reference_doctype": _BACKLOG_FILTER_DOCTYPE,
			"for_user": "",
		},
	)
	if not filter_name:
		return

	frappe.db.set_value(
		"List Filter",
		filter_name,
		"filters",
		get_backlog_filters_json()
	)


def delete_backlog_list_filter():
	"""Remove the shared Backlog List Filter on uninstall."""
	filters = frappe.db.get_all(
		"List Filter",
		filters={
			"filter_name": _BACKLOG_FILTER_NAME,
			"reference_doctype": _BACKLOG_FILTER_DOCTYPE,
			"for_user": "",
		},
		fields=["name"],
	)
	for f in filters:
		frappe.delete_doc("List Filter", f.name, ignore_permissions=True, force=True)


def after_install():
	create_roles()
	create_workflows()
	create_backlog_list_filter()
	frappe.db.commit()


def before_uninstall():
	delete_backlog_list_filter()
	delete_workflows()
