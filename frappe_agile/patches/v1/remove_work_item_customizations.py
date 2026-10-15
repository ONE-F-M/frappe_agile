import frappe


def execute():
	"""Remove every Custom Field and Property Setter on Work Item; work_item.json is its only definition."""
	for name in frappe.get_all("Custom Field", filters={"dt": "Work Item"}, pluck="name"):
		frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)

	for name in frappe.get_all("Property Setter", filters={"doc_type": "Work Item"}, pluck="name"):
		frappe.delete_doc("Property Setter", name, force=True, ignore_permissions=True)

	frappe.clear_cache(doctype="Work Item")
