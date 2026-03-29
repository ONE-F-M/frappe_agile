import frappe
from frappe_agile.setup.setup import create_backlog_list_filter

def execute():
	"""
	Run during bench migrate to create the shared Backlog List Filter
	for existing installations (like the staging server).
	"""
	create_backlog_list_filter()
	
	# Try to clear out user-specific List View overrides so the new ones show natively
	try:
		frappe.db.sql("DELETE FROM `tabUser Settings` WHERE doctype_name = 'Work Item'")
		frappe.cache().delete_keys("_user_settings")
	except Exception:
		pass
