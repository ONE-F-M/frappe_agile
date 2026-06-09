import frappe


def has_app_permission():
	"""Decide whether the Frappe Agile app shows on the apps / desktop screen.

	v16 requires this hook to return a real boolean (a falsy non-False value no
	longer grants access). We show the app to anyone who can read the core
	Work Item doctype, plus Administrator.
	"""
	if frappe.session.user == "Administrator":
		return True

	return bool(frappe.has_permission("Work Item", "read"))
