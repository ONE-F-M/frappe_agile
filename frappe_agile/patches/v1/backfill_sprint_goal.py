import frappe


def execute():
	"""Set sprint_goal to 'Existing Sprint' for all Sprint records that have no goal.

	This patch runs before the model sync so that existing records satisfy the
	mandatory sprint_goal constraint added in WI-000838.
	"""
	if not frappe.db.table_exists("Sprint"):
		return

	frappe.db.set_value(
		"Sprint",
		{"sprint_goal": ["in", ["", None]]},
		"sprint_goal",
		"Existing Sprint",
		update_modified=False,
	)

	frappe.db.commit()
