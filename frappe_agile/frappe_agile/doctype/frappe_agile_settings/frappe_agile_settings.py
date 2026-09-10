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
def get_development_team_users(project=None):
	"""Users who may take a Work Item, narrowed to ``project`` when one is given.

	The Development Team is the standing list, and a project that names its own
	users narrows it to the people on that project. A project naming nobody has
	nothing to narrow by, so the team stands as it is — otherwise every project
	without a filled-in Users table would offer no assignee at all.
	"""
	frappe.has_permission("Work Item", throw=True)
	settings = frappe.get_single("Frappe Agile Settings")
	team = [row.user for row in settings.development_team if row.user]
	if not (project and team):
		return team

	on_project = set(
		frappe.get_all(
			"Project User",
			filters={"parent": project, "parenttype": "Project"},
			pluck="user",
		)
	)
	if not on_project:
		return team
	return [user for user in team if user in on_project]

