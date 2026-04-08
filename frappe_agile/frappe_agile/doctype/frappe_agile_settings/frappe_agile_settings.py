# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FrappeAgileSettings(Document):
	pass


@frappe.whitelist()
def get_development_team_users():
	"""Return list of user emails from the Development Team table.

	Returns an empty list if no team members are configured,
	which means no filtering should be applied (show all users).
	"""
	settings = frappe.get_single("Frappe Agile Settings")
	return [row.user for row in settings.development_team if row.user]

