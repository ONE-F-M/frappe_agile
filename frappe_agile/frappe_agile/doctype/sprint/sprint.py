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

# Extra names to try past the ones already taken when the naming-series counter
# has fallen behind. Bounded by real data plus this, so naming can never spin.
NAMING_SKIP_HEADROOM = 100


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
		"""Name the sprint `<prefix>-###`, skipping numbers already in use.

		`make_autoname` trusts the stored series counter, which can lag the sprints
		that actually exist — a site restore, a bulk import or a rename all leave it
		behind. It then hands back a name that is already taken and the insert dies
		with "Sprint <name> already exists", which took out the Roadmap's
		"Create Missing Sprint(s)" for the whole project. Draw again until the name
		is free so the counter walks itself back into sync.
		"""
		if self.name or not self.sprint_prefix:
			return

		from frappe.model.naming import make_autoname

		self.sprint_prefix = self.sprint_prefix.strip()
		series = f"{self.sprint_prefix}-.###"

		# One query up front; the loop then only pays for the counter increment.
		taken = set(frappe.get_all("Sprint", filters={"sprint_prefix": self.sprint_prefix}, pluck="name"))
		for _attempt in range(len(taken) + NAMING_SKIP_HEADROOM):
			candidate = make_autoname(series)
			# `taken` covers this prefix; the exists() check also catches a sprint
			# renamed into this number range under a different prefix.
			if candidate not in taken and not frappe.db.exists("Sprint", candidate):
				self.name = candidate
				return

		frappe.throw(
			_("Could not generate a free Sprint name for prefix <b>{0}</b> — every candidate is already taken.").format(
				self.sprint_prefix
			),
			title=_("Sprint Naming Failed"),
		)

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
			# Restore the carry-forward snapshot from the pre-save DB state, since
			# the form payload may carry stale zeros after items were moved out.
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
		"business_analyst": source_doc.business_analyst,
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


def _find_next_existing_sprint(source_doc):
	"""Return the sprint that already follows *source_doc*, or None.

	"The next sprint already exists" is deliberately not tied to the exact
	Wed→Tue window: a sprint the team planned by hand, or one whose window no
	longer lines up because *source_doc* ran long or short, is still the next
	sprint. Any non-Completed Sprint of the same prefix that starts once
	*source_doc* has finished qualifies, and the earliest one wins.

	Matching on the computed window alone used to miss those and create a second
	Sprint for a week that was already planned.
	"""
	candidates = frappe.get_all(
		"Sprint",
		filters={
			"sprint_prefix": source_doc.sprint_prefix,
			"start_date": [">=", add_days(source_doc.end_date, 1)],
			"status": ["!=", "Completed"],
			"name": ["!=", source_doc.name],
		},
		pluck="name",
		order_by="start_date asc, creation asc",
		limit=1,
	)
	return candidates[0] if candidates else None


@frappe.whitelist()
def get_or_create_target_sprint(sprint_name: str) -> str:
	"""Return the sprint that should receive carry-forward items from *sprint_name*.

	  - If a non-Completed Sprint is already scheduled after this one for the same
	    prefix, reuse it (no new Sprint is created).
	  - Otherwise a new Draft Sprint is created for the next standard Wed→Tue
	    window via the naming series (never with an explicit name, so the series
	    counter stays in sync).
	"""
	doc = frappe.get_doc("Sprint", sprint_name)

	existing = _find_next_existing_sprint(doc)
	if existing:
		return existing

	return _make_new_sprint(doc)


@frappe.whitelist()
def handle_incomplete_items(sprint: str) -> str | None:
	"""Carry all not-Done Work Items of *sprint* forward to the next sprint.

	Called when a sprint is being completed. Incomplete items are never left in
	a backlog — they always move to the next sprint (reused if it already exists,
	otherwise created).

	Returns the target sprint name, or None when there is nothing to carry forward.
	"""
	# Snapshot the current velocity before any items are moved away.
	# Normalize with flt() to avoid restoring NULL into a Float field.
	current_velocity = flt(frappe.db.get_value("Sprint", sprint, "expected_velocity"))

	work_items = frappe.get_all(
		"Work Item",
		filters={"sprint": sprint, "workflow_state": ["!=", "Done"]},
		fields=["name", "work_item_type", "title", "status", "story_points", "assignee_user"],
	)

	# Nothing incomplete — no next sprint is needed or created
	if not work_items:
		return None

	# Resolve (reuse or create) the next sprint that will receive the items
	target_sprint = get_or_create_target_sprint(sprint)

	# --- Capture carried-forward snapshot BEFORE items are moved ---
	# This permanently records the spill-over on the completing sprint.
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

	# Move via frappe.db.set_value (not .save()) so _remove_from_sprint does not
	# fire and strip the completing sprint's child rows, which are kept as history.
	work_item_names = [wi.name for wi in work_items]
	for wi_name in work_item_names:
		frappe.db.set_value("Work Item", wi_name, "sprint", target_sprint)

	# Add rows to the target sprint's child table, skipping any work item already
	# present (the target may be a pre-existing draft).
	already_present = set(
		frappe.get_all(
			"Sprint Work Item",
			filters={"parent": target_sprint, "work_item": ["in", work_item_names]},
			pluck="work_item",
		)
	)
	# A row that was already planned into the reused sprint still represents work
	# spilling out of the sprint being closed, so flag it — otherwise the target's
	# brought-forward totals undercount exactly the items that carried over.
	if already_present:
		frappe.db.set_value(
			"Sprint Work Item",
			{"parent": target_sprint, "work_item": ["in", list(already_present)]},
			"is_brought_forward",
			1,
			update_modified=False,
		)
	for wi in work_items:
		if wi.name in already_present:
			continue
		frappe.get_doc({
			"doctype": "Sprint Work Item",
			"parent": target_sprint,
			"parentfield": "work_items",
			"parenttype": "Sprint",
			"work_item": wi.name,
			"work_item_type": wi.work_item_type,
			"title": wi.title,
			"status": wi.status,
			"story_points": wi.story_points,
			"assignee_user": wi.assignee_user,
			"is_brought_forward": 1,
		}).insert(ignore_permissions=True)

	# Recalculate velocity and brought-forward counts on the target sprint
	_recalculate_sprint_velocity(target_sprint)
	_recalculate_brought_forward(target_sprint)

	# Persist the velocity snapshot so it survives the form save that follows.
	frappe.db.set_value("Sprint", sprint, "expected_velocity", current_velocity, update_modified=False)

	frappe.db.commit()

	return target_sprint
