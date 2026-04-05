# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from frappe.model.document import Document
from frappe.model.naming import make_autoname


class WorkItem(Document):
	def autoname(self):
		# Use Frappe's built-in naming series to generate the next
		# atomic WI-###### identifier safely.
		self.name = make_autoname("WI-.######")

	def validate(self):
		self._validate_epic_story_points()
		self._validate_sprint_project()
		self._validate_sprint_status()


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

	def _validate_epic_story_points(self):
		"""Epics cannot have story points — they are containers, not work items."""
		if self.work_item_type == "Epic" and flt(self.story_points):
			frappe.throw(
				_("Story Points cannot be set for Epics. Story points should only be assigned to actual work items."),
				title=_("Invalid Story Points"),
			)

	def _validate_sprint_status(self):
		"""Ensure the Work Item cannot be linked to a Completed Sprint, 
		and cannot be modified if it already belongs to a Completed Sprint."""
		
		# 1. Prevent moving to or saving against a currently Completed sprint
		if self.sprint:
			sprint_status = frappe.db.get_value("Sprint", self.sprint, "status")
			if sprint_status == "Completed":
				frappe.throw(
					_("Cannot assign or update Work Item against Sprint <b>{0}</b> because it is already Completed.").format(self.sprint),
					title=_("Sprint Completed")
				)
		

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
