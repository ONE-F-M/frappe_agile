import frappe


def execute():
	"""Backfill sprint_status on all existing Work Items that have a sprint assigned.

	The sprint_status field was added after initial deployment, so existing records
	were saved before the sync hook existed. This patch ensures the field is populated
	for all of them in a single efficient query.
	"""
	if not frappe.db.has_column("Work Item", "sprint_status"):
		return

	sprints = frappe.get_all("Sprint", fields=["name", "status"])

	for sprint in sprints:
		frappe.db.set_value(
			"Work Item",
			{"sprint": sprint.name},
			"sprint_status",
			sprint.status,
			update_modified=False,
		)

	frappe.db.commit()
