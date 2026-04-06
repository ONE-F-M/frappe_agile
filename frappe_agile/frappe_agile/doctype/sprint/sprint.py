import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class Sprint(Document):
	def autoname(self):
		if not self.name and self.sprint_prefix:
			self.sprint_prefix = self.sprint_prefix.strip()
			from frappe.model.naming import make_autoname
			self.name = make_autoname(f"{self.sprint_prefix}-.###")

	def validate(self):
		self.validate_status_transition()
		self.validate_active_sprint_uniqueness()
		self.calculate_expected_velocity()

	def on_update(self):
		# Guard: skip velocity DB write during DocType schema migration context
		if not frappe.db.table_exists("tabWork Item"):
			return
		self.calculate_expected_velocity()
		self.db_set("expected_velocity", self.expected_velocity, update_modified=False)

	def validate_status_transition(self):
		"""Once a Sprint is Completed, it cannot be reverted to Draft or Active."""
		if not self.is_new():
			previous = self.get_doc_before_save()
			if previous and previous.status == "Completed" and self.status != "Completed":
				frappe.throw(
					_("A Completed Sprint cannot be reverted back to {0}.").format(self.status),
					title=_("Sprint Completed")
				)

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


@frappe.whitelist()
def get_or_create_target_sprint(sprint_name: str) -> str:
	"""
	Calculates the next sequential sprint.
	If it exists and is Draft, returns it.
	If it doesn't exist, creates it in Draft silently and returns it.
	Falls back to normal creation if the sequence is broken.
	"""
	import re
	doc = frappe.get_doc("Sprint", sprint_name)
	
	match = re.search(r'-(\d+)$', sprint_name)
	if not match:
		new_sprint = frappe.get_doc({
			"doctype": "Sprint",
			"sprint_prefix": doc.sprint_prefix,
			"project": doc.project,
			"status": "Draft",
		})
		new_sprint.insert(ignore_permissions=True)
		return new_sprint.name

	num_str = match.group(1)
	next_num = int(num_str) + 1
	target_sprint_name = f"{doc.sprint_prefix}-{str(next_num).zfill(len(num_str))}"

	if frappe.db.exists("Sprint", target_sprint_name):
		status = frappe.db.get_value("Sprint", target_sprint_name, "status")
		if status == "Draft":
			return target_sprint_name
		else:
			new_sprint = frappe.get_doc({
				"doctype": "Sprint",
				"sprint_prefix": doc.sprint_prefix,
				"project": doc.project,
				"status": "Draft",
			})
			new_sprint.insert(ignore_permissions=True)
			return new_sprint.name
	else:
		new_sprint = frappe.get_doc({
			"doctype": "Sprint",
			"name": target_sprint_name,
			"sprint_prefix": doc.sprint_prefix,
			"project": doc.project,
			"status": "Draft",
		})
		new_sprint.insert(ignore_permissions=True)
		return new_sprint.name


@frappe.whitelist()
def handle_incomplete_items(sprint: str, action: str):
	"""Handle Work Items that are not Done when a sprint is completed."""
	work_items = frappe.get_all(
		"Work Item",
		filters={"sprint": sprint, "workflow_state": ["!=", "Done"]},
		fields=["name"]
	)

	new_sprint_name = None
	if action == "Move to New Sprint":
		new_sprint_name = get_or_create_target_sprint(sprint)

	if not work_items:
		return new_sprint_name

	# Move each incomplete Work Item
	work_item_names = [wi.name for wi in work_items]
	for wi_name in work_item_names:
		frappe.db.set_value("Work Item", wi_name, "sprint", new_sprint_name or "")

	# Also remove these Work Items from the Sprint's child table
	sprintwork_rows = frappe.get_all(
		"Sprint Work Item",
		filters={"parent": sprint, "work_item": ["in", work_item_names]},
		fields=["name"]
	)
	for row in sprintwork_rows:
		frappe.delete_doc("Sprint Work Item", row.name, force=True, ignore_permissions=True)

	# If moving to new sprint, add to new sprint's child table
	if new_sprint_name:
		for wi_name in work_item_names:
			frappe.get_doc({
				"doctype": "Sprint Work Item",
				"parent": new_sprint_name,
				"parentfield": "work_items",
				"parenttype": "Sprint",
				"work_item": wi_name,
			}).insert(ignore_permissions=True)

	frappe.db.commit()

	return new_sprint_name
