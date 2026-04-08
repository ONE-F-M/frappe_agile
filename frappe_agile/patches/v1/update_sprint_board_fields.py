import frappe


def execute():
	"""Update Sprint Board Kanban card fields: replace assignee_name with assignee_user."""
	if not frappe.db.exists("Kanban Board", "Sprint Board"):
		return

	new_fields = '["title", "work_item_type", "story_points", "assignee_user", "name"]'
	frappe.db.set_value("Kanban Board", "Sprint Board", "fields", new_fields)
