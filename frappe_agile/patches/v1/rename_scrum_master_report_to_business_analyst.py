import frappe

OLD_REPORT = "Sprint Report per Scrum Master"
NEW_REPORT = "Sprint Report per Business Analyst"


def execute():
	"""Point Workspace links at the renamed sprint report and drop the old record.

	The report is standard, so migrate creates the new record from the app folder.
	"""
	links = frappe.get_all(
		"Workspace Link", filters={"link_to": OLD_REPORT, "link_type": "Report"}, pluck="name"
	)
	for link in links:
		# Saving the Workspace validates the link, which fails until the new report is imported.
		frappe.db.set_value(
			"Workspace Link",
			link,
			{"label": NEW_REPORT, "link_to": NEW_REPORT},
			update_modified=False,
		)

	if frappe.db.exists("Report", OLD_REPORT):
		frappe.delete_doc("Report", OLD_REPORT, ignore_permissions=True, force=True)

	if links:
		frappe.clear_cache()
