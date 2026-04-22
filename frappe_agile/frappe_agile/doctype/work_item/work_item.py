# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from frappe.model.document import Document
from frappe.model.naming import make_autoname


class WorkItem(Document):

	def validate(self):
		self._validate_epic_story_points()
		self._validate_sprint_project()
		self._validate_sprint_status()


	def before_save(self):
		"""
		Capture the previous sprint and ensure workflow_state is kept in sync 
		when `status` is forcefully changed via Kanban Board drag-and-drop.
		"""
		self._old_sprint = frappe.db.get_value("Work Item", self.name, "sprint")

		if self.status and self.workflow_state != self.status:
			if frappe.db.exists("Workflow State", self.status):
				self.workflow_state = self.status

	def on_update(self):
		"""
		Keep the Sprint Work Item child table in sync when the sprint
		assignment changes, then recalculate Sprint velocity.
		"""
		old_sprint = getattr(self, "_old_sprint", None)

		if old_sprint != self.sprint:
			if old_sprint:
				self._remove_from_sprint(old_sprint)
			if self.sprint:
				self._add_to_sprint(self.sprint)
		elif self.sprint:
			# Sprint didn't change, but other fields (title, status, etc.) might have
			self._sync_with_sprint(self.sprint)

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

	def _sync_with_sprint(self, sprint_name):
		"""
		Update the cached 'fetch_from' fields in the Sprint Work Item child table.
		This ensures the Sprint view stays accurate when the Work Item changes.
		"""
		frappe.db.set_value(
			"Sprint Work Item",
			{"parent": sprint_name, "work_item": self.name},
			{
				"work_item_type": self.work_item_type,
				"title": self.title,
				"status": self.status,
				"story_points": self.story_points,
				"assignee_user": self.assignee_user,
			},
			update_modified=False,
		)

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
				"work_item_type": self.work_item_type,
				"title": self.title,
				"status": self.status,
				"story_points": self.story_points,
				"assignee_user": self.assignee_user,
			},
		)
		sprint_doc.save(ignore_permissions=True)

	def _remove_from_sprint(self, sprint_name):
		"""Remove the row for this work item from Sprint.work_items."""
		frappe.db.delete("Sprint Work Item", {"parent": sprint_name, "work_item": self.name})

	def _remove_from_all_sprints(self):
		"""Remove this work item from every Sprint's child table."""
		frappe.db.delete("Sprint Work Item", {"work_item": self.name})

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
