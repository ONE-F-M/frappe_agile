import frappe


def execute():
	"""Delete the 'Sprint Report' and 'Sprint Summary' Report records from the database.

	The report files are removed as redundant. This patch cleans up the
	corresponding database records so they no longer appear in the Reports list.
	"""
	for report_name in ("Sprint Report", "Sprint Summary"):
		if frappe.db.exists("Report", report_name):
			frappe.delete_doc("Report", report_name, ignore_permissions=True, force=True)

	frappe.db.commit()
