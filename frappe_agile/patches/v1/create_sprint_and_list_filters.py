import frappe
from frappe_agile.setup.setup import create_list_filters, create_sprint_board_kanban


def execute():
	"""Apply new saved List Filters and Sprint Board kanban settings for existing installs.

	This covers:
	  - "Backlog" List Filter: sprint is not set + workflow_state != Done
	  - "Sprint Kanban List View" List Filter: sprint_status in [Active, Draft] + workflow_state != Done
	  - "Sprint Board" Kanban Board: sprint_status = Active base filter applied
	"""
	if not frappe.db.has_column("Work Item", "sprint_status"):
		# sprint_status must exist before we can apply these filters
		frappe.reload_doc("frappe_agile", "doctype", "work_item")

	create_list_filters()
	create_sprint_board_kanban()
