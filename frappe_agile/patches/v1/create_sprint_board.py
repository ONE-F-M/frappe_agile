import frappe

def execute():
	"""Create Sprint Board Kanban view for Work Item."""
	if frappe.db.exists("Kanban Board", "Sprint Board"):
		frappe.delete_doc("Kanban Board", "Sprint Board", ignore_permissions=True, force=1)
		
	# JSON fields to display on the Kanban cards
	fields = '["title", "work_item_type", "story_points", "assignee_name", "name"]'
	
	board = frappe.new_doc("Kanban Board")
	board.kanban_board_name = "Sprint Board"
	board.reference_doctype = "Work Item"
	board.field_name = "status"
	board.fields = fields
	board.show_labels = 1
	board.private = 0
	
	# Explicitly create Kanban Board Column records since Python insert does not auto-populate them
	status_options = [
		"Open", "In Progress", "Pending Action Plan", "Pending Execution", 
		"Pending PR", "Pending Review", "Changes Requested", "In Staging", 
		"Rejected", "Done"
	]
	
	for idx, status in enumerate(status_options):
		board.append("columns", {
			"column_name": status,
			"status": "Active",
			"indicator": "Gray" if status in ["Open"] else "Blue" if status in ["In Progress", "Pending Action Plan", "Pending Execution", "Pending PR", "In Staging"] else "Orange" if status in ["Pending Review", "Changes Requested"] else "Red" if status == "Rejected" else "Green"
		})

	board.insert(ignore_permissions=True)
