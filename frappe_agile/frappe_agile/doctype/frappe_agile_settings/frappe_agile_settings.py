# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


def work_item_status_options():
	"""Live list of Work Item ``status`` Select options.

	Read from the meta so the Backlog Status validation always tracks the real
	options — including any customisations — instead of a hard-coded copy.
	"""
	status_field = frappe.get_meta("Work Item").get_field("status")
	if not status_field or not status_field.options:
		return []
	return [opt.strip() for opt in status_field.options.split("\n") if opt.strip()]


class FrappeAgileSettings(Document):
	def validate(self):
		self.validate_backlog_status()

	def validate_backlog_status(self):
		"""Backlog Status is free text but replaces the Roadmap backlog's default
		statuses, so every entry must name a real Work Item status. Blank is
		allowed — the backlog then falls back to its own defaults."""
		if not self.backlog_status:
			return

		entries = [status.strip() for status in self.backlog_status.split(",") if status.strip()]
		options = work_item_status_options()
		unknown = [status for status in entries if status not in options]
		if not unknown:
			# Store it tidied, so the backlog reads exactly what was validated.
			self.backlog_status = ", ".join(entries)
			return

		frappe.throw(
			_("Backlog Status {0} is not a valid Work Item status. Choose from: {1}.").format(
				frappe.bold(", ".join(unknown)), ", ".join(options)
			),
			title=_("Invalid Backlog Status"),
		)


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

