import frappe


def execute():
	"""Delete the 'Sprint Summary (Party)' Report record from the database.

	The report files are removed in WI-000828. This patch cleans up the
	corresponding database record so it no longer appears in the Reports list.
	"""
	if frappe.db.exists("Report", "Sprint Summary (Party)"):
		frappe.delete_doc("Report", "Sprint Summary (Party)", ignore_permissions=True, force=True)
		frappe.db.commit()
