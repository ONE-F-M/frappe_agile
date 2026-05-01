import frappe


def execute():
	"""Create (or recreate) the Sprint Board Kanban view.

	Columns are aligned with the Work Item ``status`` Select field,
	which is the canonical state managed by the BPMN process engine.
	"""
	# Wipe the old board to resolve duplications and corruption
	if frappe.db.exists("Kanban Board", "Sprint Board"):
		frappe.delete_doc("Kanban Board", "Sprint Board", ignore_permissions=True, force=1)

	# JSON fields to display natively on the Kanban cards
	fields = '["title", "work_item_type", "story_points", "assignee_user", "name"]'

	board = frappe.new_doc("Kanban Board")
	board.kanban_board_name = "Sprint Board"
	board.reference_doctype = "Work Item"
	board.field_name = "status"
	board.fields = fields
	board.show_labels = 1
	board.private = 0

	# Column definitions matching the Work Item status options
	column_defs = [
		("Draft", "Gray"),
		("Open", "Gray"),
		("In Progress", "Light Blue"),
		("Pending Review", "Orange"),
		("Changes Requested", "Yellow"),
		("In Staging", "Blue"),
		("Rejected", "Red"),
		("Done", "Green"),
	]

	for idx, (col_name, indicator) in enumerate(column_defs, start=1):
		board.append("columns", {
			"column_name": col_name,
			"idx": idx,
			"status": "Active",
			"indicator": indicator,
		})

	board.insert(ignore_permissions=True)
