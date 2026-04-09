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
	which means no users will be available for selection in
	Assignee and PR Reviewer fields until the Development Team
	is configured in Frappe Agile Settings.
	"""
	frappe.has_permission("Work Item", throw=True)
	settings = frappe.get_single("Frappe Agile Settings")
	return [row.user for row in settings.development_team if row.user]

