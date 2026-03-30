import frappe

def execute():
	"""Create Sprint Board Kanban view dynamically driven by Workflow States."""
	# Always wipe the old board to resolve duplications and corruption
	if frappe.db.exists("Kanban Board", "Sprint Board"):
		frappe.delete_doc("Kanban Board", "Sprint Board", ignore_permissions=True, force=1)
		
	# JSON fields to display natively on the Kanban cards
	fields = '["title", "work_item_type", "story_points", "assignee_name", "name"]'
	
	board = frappe.new_doc("Kanban Board")
	board.kanban_board_name = "Sprint Board"
	board.reference_doctype = "Work Item"
	board.field_name = "workflow_state" # Natively track the active Workflow, not the duplicate Status field
	board.fields = fields
	board.show_labels = 1
	board.private = 0
	
	# Dynamically fetch the exact authorized order of Workflow States without hardcoding
	workflow_states = frappe.get_all(
		"Workflow Document State", 
		filters={"parent": "Work Item"}, 
		fields=["state"], 
		order_by="idx asc"
	)
	
	# If for some reason the workflow isn't installed (e.g. edge cases), fallback safely
	status_options = [row.state for row in workflow_states] if workflow_states else ["Open", "In Progress", "Pending Action Plan", "Pending Execution", "Pending PR", "Pending Review", "Changes Requested", "In Staging", "Rejected", "Done"]
	
	for idx, status in enumerate(status_options):
		# Auto-assign sensible indicator colors dynamically based on keywords
		indicator = "Blue"
		if status == "Open": indicator = "Gray"
		elif status in ("Done", "Approved"): indicator = "Green"
		elif "Pending" in status: indicator = "Orange"
		elif status == "Rejected": indicator = "Red"
		elif "In Progress" in status: indicator = "Light Blue"
			
		board.append("columns", {
			"column_name": status,
			"idx": idx + 1,
			"status": "Active",
			"indicator": indicator
		})

	board.insert(ignore_permissions=True)
