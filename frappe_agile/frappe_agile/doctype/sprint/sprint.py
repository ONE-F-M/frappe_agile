import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, date_diff, flt


class Sprint(Document):
	def autoname(self):
		if not self.name and self.sprint_prefix:
			self.sprint_prefix = self.sprint_prefix.strip()
			from frappe.model.naming import make_autoname
			self.name = make_autoname(f"{self.sprint_prefix}-.###")

	def _is_transitioning_to_completed(self):
		"""True only when an existing Sprint is being moved to Completed.

		New documents (even if inserted directly as Completed) must still
		go through velocity calculation so the field is never left stale.
		"""
		if self.is_new():
			return False
		doc_before = self.get_doc_before_save()
		return self.status == "Completed" and (not doc_before or doc_before.status != "Completed")

	def validate(self):
		self.validate_status_transition()
		self.validate_active_sprint_uniqueness()
		if not self._is_transitioning_to_completed():
			self.calculate_expected_velocity()

	def on_update(self):
		# Guard: skip velocity DB write during DocType schema migration context
		if not frappe.db.table_exists("Work Item"):
			return
		# Completed sprints have their velocity frozen — don't recalculate
		if self.status != "Completed":
			self.calculate_expected_velocity()
			self.db_set("expected_velocity", self.expected_velocity, update_modified=False)
		self.sync_sprint_status_to_work_items()

	def sync_sprint_status_to_work_items(self):
		"""Push this Sprint's current status into sprint_status on all linked Work Items.

		Called on every Sprint save so that the Fetch From cache stays accurate
		even for existing Work Items that were saved before the sprint changed state.
		We only write when the status has actually changed to avoid redundant updates.
		"""
		if not frappe.db.has_column("Work Item", "sprint_status"):
			return

		doc_before = self.get_doc_before_save()
		if doc_before and doc_before.status == self.status:
			# Status unchanged — nothing to sync
			return

		frappe.db.set_value(
			"Work Item",
			{"sprint": self.name},
			"sprint_status",
			self.status,
			update_modified=False,
		)

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
		"""Sum story_points of all Work Items linked to this sprint.

		Completed sprints have their velocity frozen — the value at completion
		time is preserved as a historical "planned scope" metric.
		"""
		# Freeze: never overwrite a Completed sprint's velocity
		if self.status == "Completed":
			return

		if not self.name or not frappe.db.table_exists("tabWork Item"):
			self.expected_velocity = 0.0
			return

		from frappe.query_builder import DocType
		from frappe.query_builder.functions import Coalesce, Sum

		WorkItem = DocType("Work Item")
		result = (
			frappe.qb.from_(WorkItem)
			.select(Coalesce(Sum(WorkItem.story_points), 0).as_("total"))
			.where(WorkItem.sprint == self.name)
		).run(as_dict=True)

		self.expected_velocity = flt(result[0].total if result else 0, 2)


# ---------------------------------------------------------------------------
# Module-level helpers called via doc_events from hooks.py
# ---------------------------------------------------------------------------


def _recalculate_sprint_velocity(sprint_name: str):
	"""Recalculate and persist expected_velocity for a single Sprint.

	Completed sprints are frozen — their velocity is never recalculated.
	"""
	if not sprint_name or not frappe.db.exists("Sprint", sprint_name):
		return

	# Don't touch Completed sprints — velocity is frozen at completion time
	status = frappe.db.get_value("Sprint", sprint_name, "status")
	if status == "Completed":
		return

	from frappe.query_builder import DocType
	from frappe.query_builder.functions import Coalesce, Sum

	WorkItem = DocType("Work Item")
	result = (
		frappe.qb.from_(WorkItem)
		.select(Coalesce(Sum(WorkItem.story_points), 0).as_("total"))
		.where(WorkItem.sprint == sprint_name)
	).run(as_dict=True)

	velocity = flt(result[0].total if result else 0, 2)
	frappe.db.set_value("Sprint", sprint_name, "expected_velocity", velocity, update_modified=False)


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
		_recalculate_sprint_velocity(sprint_name)


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


def _build_new_sprint_dates(source_doc):
	"""Derive start_date and end_date for a new sprint from the source sprint.

	start_date = source end_date + 1 day
	end_date   = start_date + same duration as the source sprint
	"""
	duration = date_diff(source_doc.end_date, source_doc.start_date)
	new_start = add_days(source_doc.end_date, 1)
	new_end = add_days(new_start, duration)
	return new_start, new_end


def _make_new_sprint(source_doc, extra_fields=None):
	"""Create and insert a new Draft Sprint derived from *source_doc*.

	Dates are computed lazily — only called from branches that actually need
	a new Sprint document.
	"""
	new_start, new_end = _build_new_sprint_dates(source_doc)
	values = {
		"doctype": "Sprint",
		"sprint_prefix": source_doc.sprint_prefix,
		"project": source_doc.project,
		"status": "Draft",
		"start_date": new_start,
		"end_date": new_end,
		"sprint_goal": _("Carry Forward"),
	}
	if extra_fields:
		values.update(extra_fields)

	new_sprint = frappe.get_doc(values)
	new_sprint.insert(ignore_permissions=True)
	return new_sprint.name


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
		return _make_new_sprint(doc)

	num_str = match.group(1)
	next_num = int(num_str) + 1
	target_sprint_name = f"{doc.sprint_prefix}-{str(next_num).zfill(len(num_str))}"

	if frappe.db.exists("Sprint", target_sprint_name):
		status = frappe.db.get_value("Sprint", target_sprint_name, "status")
		if status == "Draft":
			return target_sprint_name
		else:
			return _make_new_sprint(doc)
	else:
		return _make_new_sprint(doc, {"name": target_sprint_name})


@frappe.whitelist()
def handle_incomplete_items(sprint: str, action: str):
	"""Handle Work Items that are not Done when a sprint is completed."""
	# Snapshot the current velocity before any items are moved away.
	# Normalize with flt() to avoid restoring NULL into a Float field.
	current_velocity = flt(frappe.db.get_value("Sprint", sprint, "expected_velocity"))

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

	# Clean up child table rows from the completing sprint
	for wi_name in work_item_names:
		frappe.db.delete("Sprint Work Item", {"parent": sprint, "work_item": wi_name})

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
		# Recalculate velocity on the new sprint that gained items
		_recalculate_sprint_velocity(new_sprint_name)

	# NOTE: We intentionally do NOT recalculate velocity on the completing
	# sprint.  Its velocity will be frozen by calculate_expected_velocity()
	# when the Sprint is saved with status = "Completed" immediately after.

	# Restore the velocity snapshot — guards in update_sprint_velocity should
	# prevent overwrites, but this is a safety net
	frappe.db.set_value("Sprint", sprint, "expected_velocity", current_velocity, update_modified=False)

	frappe.db.commit()

	return new_sprint_name
