import frappe


def execute():
	"""Delete the 'Sprint Report' and 'Sprint Summary' Report records and
	remove their links from the Frappe Agile Workspace.

	The report files have been removed as redundant. This patch cleans up:
	1. The Report documents from the database.
	2. The corresponding Workspace Link child-table rows.
	3. The Reports card break link_count.
	"""
	# 1. Delete Report documents
	for report_name in ("Sprint Report", "Sprint Summary"):
		if frappe.db.exists("Report", report_name):
			frappe.delete_doc("Report", report_name, ignore_permissions=True, force=True)

	# 2. Remove the Workspace Link rows for the deleted reports
	workspace_name = "Frappe Agile"
	if frappe.db.exists("Workspace", workspace_name):
		workspace = frappe.get_doc("Workspace", workspace_name)

		# Filter out the two report links
		removed_labels = {"Sprint Report", "Sprint Summary"}
		workspace.links = [
			link for link in workspace.links
			if link.label not in removed_labels
		]

		# Update the Reports card break link_count to 0
		for link in workspace.links:
			if link.type == "Card Break" and link.label == "Reports":
				link.link_count = 0

		workspace.save(ignore_permissions=True)

	frappe.db.commit()
