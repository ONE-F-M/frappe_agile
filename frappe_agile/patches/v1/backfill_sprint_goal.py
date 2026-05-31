import frappe


def execute():
	"""Set sprint_goal to 'Existing Sprint' for all Sprint records that have no goal.

	This patch runs before the model sync so that existing records satisfy the
	mandatory sprint_goal constraint added in WI-000838.

	Because it runs pre_model_sync, the column may not yet exist in the database.
	If missing, we add it first so the backfill can proceed before the schema
	migration enforces the NOT NULL constraint.
	"""
	if not frappe.db.table_exists("Sprint"):
		return

	if not frappe.db.has_column("Sprint", "sprint_goal"):
		frappe.db.sql_ddl(
			"ALTER TABLE `tabSprint` ADD COLUMN `sprint_goal` text"
		)

	sprints = frappe.get_all(
		"Sprint",
		filters={"sprint_goal": ["in", ["", None]]},
		fields=["name"],
	)

	for sprint in sprints:
		frappe.db.set_value(
			"Sprint",
			sprint.name,
			"sprint_goal",
			"Existing Sprint",
			update_modified=False,
		)

	frappe.db.commit()
