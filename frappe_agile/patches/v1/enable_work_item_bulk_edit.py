import frappe

def execute():
	"""Enable bulk editing for Work Item by setting allow_edit in List View Settings."""
	if frappe.db.exists("List View Settings", "Work Item"):
		frappe.db.set_value("List View Settings", "Work Item", "allow_edit", 1)
	else:
		frappe.get_doc({
			"doctype": "List View Settings",
			"name": "Work Item",
			"allow_edit": 1,
		}).insert(ignore_permissions=True)
