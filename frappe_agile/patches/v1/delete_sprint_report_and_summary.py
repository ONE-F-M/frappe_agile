import frappe


def execute():
	"""Delete the 'Sprint Report' and 'Sprint Summary' Report records,
	remove their links from the Frappe Agile Workspace, and add the
	replacement report links.

	This patch cleans up:
	1. The Report documents from the database.
	2. The corresponding Workspace Link child-table rows.
	3. Adds AI Usage Report, Sprint Report per Business Analyst, and
	   Sprint Report per Developer to the Reports card.
	"""
	# 1. Delete Report documents
	for report_name in ("Sprint Report", "Sprint Summary"):
		if frappe.db.exists("Report", report_name):
			frappe.delete_doc("Report", report_name, ignore_permissions=True, force=True)

	# 2. Update the Workspace
	workspace_name = "Frappe Agile"
	if not frappe.db.exists("Workspace", workspace_name):
		return

	workspace = frappe.get_doc("Workspace", workspace_name)

	# Remove the two old report links
	removed_labels = {"Sprint Report", "Sprint Summary"}
	workspace.links = [
		link for link in workspace.links
		if link.label not in removed_labels
	]

	# Define the new report links to add
	new_reports = [
		{
			"label": "AI Usage Report",
			"link_to": "AI Usage Report",
		},
		{
			"label": "Sprint Report per BA",
			"link_to": "Sprint Report per Business Analyst",
		},
		{
			"label": "Sprint Report per Developer",
			"link_to": "Sprint Report per Developer",
		},
	]

	# Collect labels already present to avoid duplicates
	existing_labels = {link.label for link in workspace.links}

	for report in new_reports:
		if report["label"] not in existing_labels:
			workspace.append("links", {
				"hidden": 0,
				"is_query_report": 1,
				"label": report["label"],
				"link_count": 0,
				"link_to": report["link_to"],
				"link_type": "Report",
				"onboard": 0,
				"type": "Link",
			})

	# Update the Reports card break link_count
	for link in workspace.links:
		if link.type == "Card Break" and link.label == "Reports":
			link.link_count = 3

	workspace.save(ignore_permissions=True)
	frappe.db.commit()
