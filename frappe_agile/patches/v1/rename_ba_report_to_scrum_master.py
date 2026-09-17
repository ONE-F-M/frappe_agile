import frappe

OLD_REPORT = "Sprint Report per Business Analyst"
NEW_REPORT = "Sprint Report per Scrum Master"


def execute():
	"""Retire the Business Analyst sprint report in favour of the Scrum Master one.

	The report is standard, so migrate creates the new record from the app folder;
	this repoints the Workspace link and drops the old record.
	"""
	links = frappe.get_all(
		"Workspace Link", filters={"link_to": OLD_REPORT, "link_type": "Report"}, pluck="name"
	)
	for link in links:
		# Written field by field: saving the Workspace validates the link, which
		# fails while the replacement report has not been imported yet.
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
	frappe.db.commit()
