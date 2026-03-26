import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class Sprint(Document):
	def validate(self):
		self.validate_active_sprint_uniqueness()
		self.calculate_expected_velocity()

	def on_update(self):
		# Guard: skip velocity DB write during DocType schema migration context
		if not frappe.db.table_exists("tabWork Item"):
			return
		self.calculate_expected_velocity()
		self.db_set("expected_velocity", self.expected_velocity, update_modified=False)

	def validate_active_sprint_uniqueness(self):
		"""Prevent two sprints with the same prefix from being Active simultaneously."""
		if self.status != "Active":
			return

		duplicate = frappe.db.exists(
			"Sprint",
			{
				"sprint_prefix": self.sprint_prefix,
				"status": "Active",
				"name": ("!=", self.name or ""),
			},
		)

		if duplicate:
			frappe.throw(
				msg=_(
					"Sprint {0} with prefix <b>{1}</b> is already Active. "
					"Only one Sprint per prefix can be Active at a time."
				).format(duplicate, self.sprint_prefix),
				title=_("Duplicate Active Sprint"),
			)

	def calculate_expected_velocity(self):
		"""Sum story_points of all Work Items linked to this sprint."""
		if not self.name or not frappe.db.table_exists("tabWork Item"):
			self.expected_velocity = 0.0
			return

		result = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(story_points), 0) AS total
			FROM `tabWork Item`
			WHERE sprint = %s
			""",
			(self.name,),
			as_dict=True,
		)

		self.expected_velocity = flt(result[0].total if result else 0, 2)


# ---------------------------------------------------------------------------
# Module-level helpers called via doc_events from hooks.py
# ---------------------------------------------------------------------------


def update_sprint_velocity(doc, method=None):
	"""
	Recalculate expected_velocity on the linked Sprint(s) whenever a
	Work Item is saved or deleted.

	Handles the case where the Work Item's sprint field changes — both
	the old and the new sprint are updated.
	"""
	sprints_to_update = set()

	# Sprint that is currently set on the Work Item
	if doc.sprint:
		sprints_to_update.add(doc.sprint)

	# Sprint that was previously set (before this save), if any
	doc_before = doc.get_doc_before_save()
	if doc_before and doc_before.sprint and doc_before.sprint != doc.sprint:
		sprints_to_update.add(doc_before.sprint)

	for sprint_name in sprints_to_update:
		if not frappe.db.exists("Sprint", sprint_name):
			continue

		total = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(story_points), 0) AS total
			FROM `tabWork Item`
			WHERE sprint = %s
			""",
			(sprint_name,),
			as_dict=True,
		)

		velocity = flt(total[0].total if total else 0, 2)
		frappe.db.set_value("Sprint", sprint_name, "expected_velocity", velocity, update_modified=False)


def validate_work_item_sprint(doc, method=None):
	"""
	Ensure a Work Item can only be assigned to a Sprint whose Project
	matches the Work Item's Project.
	"""
	if not doc.sprint:
		return

	sprint_project = frappe.db.get_value("Sprint", doc.sprint, "project")

	# If either the Sprint or the Work Item has no project set, skip the check
	if not sprint_project or not doc.project:
		return

	if doc.project != sprint_project:
		frappe.throw(
			msg=_(
				"Work Item project <b>{0}</b> does not match Sprint <b>{1}</b> project <b>{2}</b>. "
				"A Work Item can only be assigned to a Sprint in the same Project."
			).format(doc.project, doc.sprint, sprint_project),
			title=_("Project Mismatch"),
		)
