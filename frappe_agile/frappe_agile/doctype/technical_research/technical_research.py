# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappe_agile.frappe_agile.doctype.sprint.sprint import get_or_create_target_sprint


class TechnicalResearch(Document):
	def on_submit(self):
		if self.create_work_items != "Yes":
			return

		rows = self.get("work_item") or []
		if not rows:
			return

		sprint = get_or_create_target_sprint(self._researched_sprint())
		project = frappe.db.get_value("Sprint", sprint, "project")

		for row in rows:
			frappe.get_doc(
				{
					"doctype": "Work Item",
					"work_item_type": row.work_item_type,
					"title": row.title,
					"description": row.description,
					"assignee_user": self.assignee,
					"sprint": sprint,
					"project": project,
				}
			).insert()

	def _researched_sprint(self):
		"""The sprint the researched work item sits on; its successor takes the new items.

		The research is raised from a Work Item that is already on a sprint, and that
		sprint is under way by the time the findings land — so the work it calls for
		belongs to the one after it.
		"""
		if not self.source_work_item:
			frappe.throw(
				_(
					"This research is not linked to a Work Item, so there is no sprint to plan "
					"the new work items into. Set Create Work Items to No, or raise the research "
					"from a Work Item."
				),
				title=_("No Source Work Item"),
			)

		sprint = frappe.db.get_value("Work Item", self.source_work_item, "sprint")
		if not sprint:
			frappe.throw(
				_("Work Item {0} is not on a sprint, so there is no next sprint to plan into.").format(
					self.source_work_item
				),
				title=_("Source Work Item Has No Sprint"),
			)

		return sprint
