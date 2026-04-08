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
		["Work Item", "sprint", "is", "not set", False],
		["Work Item", "workflow_state", "!=", "Done", False],
		["Work Item", "work_item_type", "!=", "Epic", False]
	]
	return json.dumps(filters)


def get_sprint_list_filters_json() -> str:
	"""Generate the filters JSON for the Sprint Kanban List View saved filter."""
	filters = [
		["Work Item", "sprint_status", "in", ["Active", "Draft"], False],
		["Work Item", "workflow_state", "!=", "Done", False],
		["Work Item", "work_item_type", "!=", "Epic", False]
	]
	return json.dumps(filters)


def create_list_filters():
	"""Create default List Filters for Work Item."""
	filters_to_create = [
		{
			"filter_name": _BACKLOG_FILTER_NAME,
			"reference_doctype": _BACKLOG_FILTER_DOCTYPE,
			"filters": get_backlog_filters_json()
		},
		{
			"filter_name": "Sprint Kanban List View",
			"reference_doctype": "Work Item",
			"filters": get_sprint_list_filters_json()
		}
	]

	for f in filters_to_create:
		existing = frappe.db.get_value(
			"List Filter",
			{
				"filter_name": f["filter_name"],
				"reference_doctype": f["reference_doctype"],
				"for_user": "",
			},
		)
		if existing:
			frappe.db.set_value("List Filter", existing, "filters", f["filters"])
		else:
			frappe.get_doc(
				{
					"doctype": "List Filter",
					"filter_name": f["filter_name"],
					"reference_doctype": f["reference_doctype"],
					"for_user": "",
					"filters": f["filters"],
				}
			).insert(ignore_permissions=True)


def create_sprint_board_kanban():
	"""Create standard Sprint Board Kanban Board."""
	filters_json = json.dumps([
		["Work Item", "sprint_status", "=", "Active", False],
		["Work Item", "work_item_type", "!=", "Epic", False]
	])
	
	if not frappe.db.exists("Kanban Board", "Sprint Board"):
		# In a Kanban Board, columns are added automatically based on the field if not supplied. 
		# But since the workflow state is mapped, the user already stated:
		# "we've already have kanban board with workflow state represent each board."
		# so it exists or normally gets created via UI. We still provide fallback creation.
		try:
			doc = frappe.get_doc({
				"doctype": "Kanban Board",
				"kanban_board_name": "Sprint Board",
				"reference_doctype": "Work Item",
				"field_name": "workflow_state",
				"filters": filters_json
			})
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(
				title="Failed to create Sprint Board Kanban Board",
				message=frappe.get_traceback(),
			)
	else:
		frappe.db.set_value("Kanban Board", "Sprint Board", "filters", filters_json)


def delete_backlog_list_filter():
	"""Remove shared List Filters on uninstall."""
	filters = frappe.db.get_all(
		"List Filter",
		filters={
			"filter_name": ["in", [_BACKLOG_FILTER_NAME, "Sprint Kanban List View"]],
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
	create_list_filters()
	create_sprint_board_kanban()
	frappe.db.commit()

def before_uninstall():
	delete_backlog_list_filter()
	delete_workflows()
