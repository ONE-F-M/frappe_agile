import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate

# --- Sprint cadence -------------------------------------------------------
# Sprints run Wednesday → Tuesday (a 7-day window) unless explicitly overridden
# ("stated otherwise"). These constants/helpers are the single source of truth
# for that cadence and are reused by the Roadmap board.
SPRINT_START_WEEKDAY = 2  # Monday=0 … Wednesday=2
SPRINT_SPAN_DAYS = 6  # start + 6 days = the following Tuesday (7-day window)


def align_to_sprint_start(d):
	"""Return the sprint-start weekday (Wednesday) on or after date *d*."""
	d = getdate(d)
	return add_days(d, (SPRINT_START_WEEKDAY - d.weekday()) % 7)


def default_sprint_window(reference_date=None):
	"""(start, end) of the standard Wed→Tue window starting on/after *reference_date*."""
	start = align_to_sprint_start(reference_date or getdate())
	return start, add_days(start, SPRINT_SPAN_DAYS)


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

		if self._is_transitioning_to_completed():
			# Bug fix: the form payload that triggered this save may carry
			# expected_velocity = 0 (the client value dropped when items were
			# moved out by handle_incomplete_items).  Restore from the
			# pre-save DB snapshot, which was correctly set by
			# handle_incomplete_items before frm.save() was called.
			# The same applies to stories_carried_forward and
			# points_carried_forward which are also set by
			# handle_incomplete_items before the client save.
			doc_before = self.get_doc_before_save()
			if doc_before is not None:
				self.db_set(
					{
						"expected_velocity": doc_before.expected_velocity,
						"stories_carried_forward": doc_before.stories_carried_forward,
						"points_carried_forward": doc_before.points_carried_forward,
					},
					update_modified=False,
				)
			# Compute accepted points once, just before freezing, on Active→Completed
			_recalculate_accepted_points(self.name, force=True)
		elif self.status != "Completed":
			# Active / Draft sprint — recalculate from current Work Items
			self.calculate_expected_velocity()
			self.db_set("expected_velocity", self.expected_velocity, update_modified=False)
			_recalculate_accepted_points(self.name)

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

		if not self.name or not frappe.db.table_exists("Work Item"):
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


def _recalculate_brought_forward(sprint_name: str):
	"""Recalculate and persist stories_brought_forward and points_brought_forward.

	Counts Sprint Work Item child rows where is_brought_forward == 1,
	which are set when a Work Item moves into this sprint from a different sprint.
	"""
	if not sprint_name or not frappe.db.exists("Sprint", sprint_name):
		return

	if not frappe.db.table_exists("Sprint Work Item"):
		return

	# Guard against being called before bench migrate has added the new columns
	if not frappe.db.has_column("Sprint", "stories_brought_forward"):
		return

	from frappe.query_builder import DocType
	from frappe.query_builder.functions import Coalesce, Count, Sum

	SWI = DocType("Sprint Work Item")
	result = (
		frappe.qb.from_(SWI)
		.select(
			Count(SWI.name).as_("stories"),
			Coalesce(Sum(SWI.story_points), 0).as_("points"),
		)
		.where(SWI.parent == sprint_name)
		.where(SWI.is_brought_forward == 1)
	).run(as_dict=True)

	row = result[0] if result else {}
	stories = cint(row.get("stories", 0))
	points = flt(row.get("points", 0), 1)

	frappe.db.set_value(
		"Sprint",
		sprint_name,
		{
			"stories_brought_forward": stories,
			"points_brought_forward": points,
		},
		update_modified=False,
	)


def _recalculate_accepted_points(sprint_name: str, force: bool = False):
	"""Recalculate and persist points_accepted for a single Sprint.

	Accepted points = sum of story_points of Work Items in this sprint
	with status == 'Done'.
	Completed sprints are frozen — their accepted points are not recalculated
	unless force=True (used only on the Active→Completed transition).
	"""
	if not sprint_name or not frappe.db.exists("Sprint", sprint_name):
		return

	# Don't touch Completed sprints — accepted points are frozen at completion time
	# Exception: force=True is used once on the transition itself
	if not force:
		status = frappe.db.get_value("Sprint", sprint_name, "status")
		if status == "Completed":
			return

	if not frappe.db.table_exists("Work Item"):
		return

	from frappe.query_builder import DocType
	from frappe.query_builder.functions import Coalesce, Sum

	WorkItem = DocType("Work Item")
	result = (
		frappe.qb.from_(WorkItem)
		.select(Coalesce(Sum(WorkItem.story_points), 0).as_("total"))
		.where(WorkItem.sprint == sprint_name)
		.where(WorkItem.status == "Done")
	).run(as_dict=True)

	accepted = flt(result[0].total if result else 0, 1)
	frappe.db.set_value("Sprint", sprint_name, "points_accepted", accepted, update_modified=False)


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
		_recalculate_brought_forward(sprint_name)
		_recalculate_accepted_points(sprint_name)


def _build_new_sprint_dates(source_doc):
	"""Derive Wed→Tue start/end for the next sprint after *source_doc*.

	The next sprint begins on the first sprint-start weekday (Wednesday) after the
	source sprint ends and runs the standard 7-day window (through Tuesday),
	regardless of the source sprint's own length.
	"""
	new_start = align_to_sprint_start(add_days(source_doc.end_date, 1))
	return new_start, add_days(new_start, SPRINT_SPAN_DAYS)


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
		fields=["name", "story_points"]
	)

	new_sprint_name = None
	if action == "Move to New Sprint":
		new_sprint_name = get_or_create_target_sprint(sprint)

	if not work_items:
		return new_sprint_name

	# --- Capture carried-forward snapshot BEFORE items are moved ---
	# This permanently records the spill-over on the completing sprint.
	# Only written when there are actually incomplete items (otherwise the
	# default value of 0 is already correct, and writing before commit is safe).
	stories_cf = len(work_items)
	points_cf = flt(sum(flt(wi.story_points) for wi in work_items), 1)
	frappe.db.set_value(
		"Sprint",
		sprint,
		{
			"stories_carried_forward": stories_cf,
			"points_carried_forward": points_cf,
		},
		update_modified=False,
	)

	# Move each incomplete Work Item to the target destination.
	# We use frappe.db.set_value() (not Work Item .save()) to avoid triggering
	# _remove_from_sprint, which would try to modify the completing sprint's
	# child table — the table is now intentionally left intact as a frozen
	# historical record.
	work_item_names = [wi.name for wi in work_items]
	for wi_name in work_item_names:
		frappe.db.set_value("Work Item", wi_name, "sprint", new_sprint_name or "")

	# Bug fix: do NOT delete Sprint Work Item rows from the completing sprint.
	# Those rows stay as a frozen historical record of what was in-flight when
	# the sprint closed.  The freeze is enforced naturally:
	#   - _remove_from_sprint() guards against Completed sprints.
	#   - _sync_with_sprint() uses doc.sprint (new / empty) as the parent,
	#     so it will never overwrite the completing sprint's historical rows.

	# If moving to new sprint, add rows to that sprint's child table
	if new_sprint_name:
		for wi_name in work_item_names:
			frappe.get_doc({
				"doctype": "Sprint Work Item",
				"parent": new_sprint_name,
				"parentfield": "work_items",
				"parenttype": "Sprint",
				"work_item": wi_name,
				"is_brought_forward": 1,
			}).insert(ignore_permissions=True)
		# Recalculate velocity and brought-forward counts on the new sprint
		_recalculate_sprint_velocity(new_sprint_name)
		_recalculate_brought_forward(new_sprint_name)

	# Persist the velocity snapshot so it survives the form save that
	# immediately follows this call.  on_update will restore it again from
	# doc_before as a belt-and-suspenders guard.
	frappe.db.set_value("Sprint", sprint, "expected_velocity", current_velocity, update_modified=False)

	frappe.db.commit()

	return new_sprint_name
