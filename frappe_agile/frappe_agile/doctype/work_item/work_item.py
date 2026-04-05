# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class WorkItem(Document):
	def autoname(self):
		# Fetch the count of current documents securely via Frappe ORM
		current_count = frappe.db.count("Work Item")
		next_sequence = current_count + 1
		
		# Set the name explicitly to the correct 6-digit zero-padded sequence
		self.name = f"WI-{str(next_sequence).zfill(6)}"

	def validate(self):
		self._validate_sprint_project()

	def before_insert(self):
		"""Add this work item to the Sprint's child table on creation."""
		if self.sprint:
			self._add_to_sprint(self.sprint)

	def before_save(self):
		"""
		Ensure workflow_state is kept in sync when `status` is forcefully
		changed via Kanban Board drag-and-drop.
		"""
		if self.status and self.workflow_state != self.status:
			if frappe.db.exists("Workflow State", self.status):
				self.workflow_state = self.status

	def on_update(self):
		"""
		Keep the Sprint Work Item child table in sync when the sprint
		assignment changes, then recalculate Sprint velocity.
		"""
		previous = self.get_doc_before_save()
		old_sprint = previous.sprint if previous else None

		if old_sprint != self.sprint:
			if old_sprint:
				self._remove_from_sprint(old_sprint)
			if self.sprint:
				self._add_to_sprint(self.sprint)

		# Update velocity on affected sprints
		from frappe_agile.frappe_agile.doctype.sprint.sprint import update_sprint_velocity
		update_sprint_velocity(self)

	def on_trash(self):
		"""Remove this work item from all Sprint child tables then re-calc velocity."""
		self._remove_from_all_sprints()

		# Recalculate velocity for the affected sprint
		from frappe_agile.frappe_agile.doctype.sprint.sprint import update_sprint_velocity
		update_sprint_velocity(self)

	# ------------------------------------------------------------------
	# Private helpers — Sprint Work Item child table management
	# ------------------------------------------------------------------

	def _add_to_sprint(self, sprint_name):
		"""Append a row to Sprint.work_items for this work item."""
		if not frappe.db.exists("Sprint", sprint_name):
			return

		sprint_doc = frappe.get_doc("Sprint", sprint_name)

		# Avoid duplicate rows
		if any(row.work_item == self.name for row in sprint_doc.get("work_items", [])):
			return

		sprint_doc.append(
			"work_items",
			{
				"work_item": self.name,
			},
		)
		sprint_doc.save(ignore_permissions=True)

	def _remove_from_sprint(self, sprint_name):
		"""Remove the row for this work item from Sprint.work_items."""
		if not frappe.db.exists("Sprint", sprint_name):
			return

		sprint_doc = frappe.get_doc("Sprint", sprint_name)
		rows_to_remove = [
			row for row in sprint_doc.get("work_items", []) if row.work_item == self.name
		]
		for row in rows_to_remove:
			sprint_doc.remove(row)
		if rows_to_remove:
			sprint_doc.save(ignore_permissions=True)

	def _remove_from_all_sprints(self):
		"""Remove this work item from every Sprint's child table."""
		sprint_rows = frappe.db.get_all(
			"Sprint Work Item",
			filters={"work_item": self.name},
			fields=["parent"],
			distinct=True,
		)
		for row in sprint_rows:
			self._remove_from_sprint(row["parent"])

	def _validate_sprint_project(self):
		"""Ensure the Work Item's project matches the Sprint's project."""
		if not self.sprint or not self.project:
			return

		sprint_project = frappe.db.get_value("Sprint", self.sprint, "project")
		if sprint_project and sprint_project != self.project:
			frappe.throw(
				_(
					"Work Item Project <b>{0}</b> does not match Sprint Project <b>{1}</b>. "
					"A Work Item can only be assigned to a Sprint that belongs to the same project."
				).format(self.project, sprint_project),
				title=_("Project Mismatch"),
			)


# ---------------------------------------------------------------------------
# Module-level helper called via doc_events in hooks.py
# ---------------------------------------------------------------------------


def sync_status_from_workflow(doc, method=None):
	"""
	Keep the `status` Select field in sync with `workflow_state`.

	When a Workflow action fires (e.g. "Start Work"), Frappe sets
	`workflow_state` but does NOT automatically mirror it to the
	`status` field.  This hook bridges that gap so both fields
	always reflect the same value.

	Direction: workflow_state  →  status
	(The `before_save` hook on the controller handles the reverse
	direction for Kanban drag-and-drop: status → workflow_state.)
	"""
	if not doc.workflow_state:
		return

	# Only sync when workflow_state is a known status option
	valid_statuses = [
		"Open",
		"In Progress",
		"Pending Action Plan",
		"Pending Execution",
		"Pending PR",
		"Pending Review",
		"Changes Requested",
		"In Staging",
		"Rejected",
		"Done",
	]

	if doc.workflow_state in valid_statuses and doc.status != doc.workflow_state:
		doc.status = doc.workflow_state
