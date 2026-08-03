# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

"""Server-side data provider for the Roadmap board page.

The Roadmap renders a Kanban-style grid:
  - Rows    = a "lane" (sprint prefix, or linked Project) — each lane runs a
              sequence of sprints over time.
  - Columns = weekly time windows, aligned across lanes by sprint start_date.
              The axis is extended with empty *future* windows so work can be
              planned ahead and dragged into upcoming sprints.
  - Cells   = the Sprint that falls in that (lane, window), with its status,
              story-point acceptance %, and the list of work items (each shown
              with a checkbox marking whether the item is accepted / Done).

Acceptance is computed live from the work items rather than from the stored
`points_accepted` field so the board is always accurate even if that cached
field is stale.

Work items can be moved between sprints via `move_work_item` (drag & drop on
the client). Dropping into an empty future slot auto-creates a Draft Sprint for
that lane/window.

Sprint creation (both the drop-into-empty-slot path and the "create missing
sprints" bulk action) is only available when grouping by **project**. A Sprint
requires a Project, and its `sprint_prefix` is read-only and fetched from
`project.custom_sprint_prefix` — so the project has to be known up front, and
only the project lane supplies it. Under sprint-prefix grouping the lane is a
bare prefix string that does not identify a project, so creation is refused
there rather than guessed at.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate

# A work item is considered "accepted" when it reaches this status.
ACCEPTED_STATUS = "Done"

# Default number of empty future sprint windows to project forward for planning.
DEFAULT_FUTURE_COUNT = 8

# Sprints run Wednesday → Tuesday (7-day window). The cadence helpers live on the
# Sprint controller so the board and the doctype stay in lock-step.
from frappe_agile.frappe_agile.doctype.sprint.sprint import (  # noqa: E402
	SPRINT_SPAN_DAYS,
	align_to_sprint_start,
)


@frappe.whitelist()
def get_roadmap_data(group_by="sprint_prefix", lane=None, sprint_status=None, search=None, future_count=None):
	"""Return the full roadmap grid.

	Args:
		group_by: "sprint_prefix" (default) or "project" — controls the row axis.
		lane: optional, restrict to a single lane (prefix or project value).
		sprint_status: optional, restrict to sprints in this status.
		search: optional, free-text filter on work item title / sprint name.
		future_count: how many empty future sprint windows to append for planning.

	Returns dict: {columns: [...], rows: [...], cells: {cell_key: {...}}}
	"""
	if group_by not in ("sprint_prefix", "project"):
		group_by = "sprint_prefix"

	frappe.has_permission("Sprint", "read", throw=True)
	frappe.has_permission("Work Item", "read", throw=True)

	future_count = cint(future_count) if future_count not in (None, "") else DEFAULT_FUTURE_COUNT
	sprint_filters = {}
	if sprint_status:
		sprint_filters["status"] = sprint_status
	if lane:
		sprint_filters[group_by] = lane

	sprints = frappe.get_list(
		"Sprint",
		filters=sprint_filters,
		fields=[
			"name",
			"sprint_prefix",
			"project",
			"status",
			"start_date",
			"end_date",
			"sprint_goal",
			"expected_velocity",
			"points_accepted",
			"target_points",
		],
		order_by="start_date asc, name asc",
		limit_page_length=0,
	)

	if not sprints:
		return {"columns": [], "rows": [], "cells": {}, "group_by": group_by}

	# --- Fetch all work items for these sprints in one query ---
	sprint_names = [s.name for s in sprints]
	work_items = frappe.get_list(
		"Work Item",
		filters={"sprint": ["in", sprint_names]},
		fields=[
			"name",
			"title",
			"work_item_type",
			"status",
			"story_points",
			"sprint",
			"epic",
			"assignee_user",
		],
		order_by="story_points desc, name asc",
		limit_page_length=0,
	)

	search_term = (search or "").strip().lower()

	# Resolve the title of every Epic referenced by a work item so cells can group
	# their items under a readable epic name (the `epic` field only stores the id).
	epic_titles = _epic_titles([wi.epic for wi in work_items])

	items_by_sprint = {}
	for wi in work_items:
		items_by_sprint.setdefault(wi.sprint, []).append(wi)

	# --- Build the column axis: distinct start_date windows, chronological ---
	windows = {}
	for s in sprints:
		if not s.start_date:
			continue
		col_key = getdate(s.start_date).isoformat()
		win = windows.setdefault(
			col_key,
			{"key": col_key, "start_date": s.start_date, "end_date": s.end_date},
		)
		# Keep the latest end_date seen for the column header range
		if s.end_date and (not win["end_date"] or getdate(s.end_date) > getdate(win["end_date"])):
			win["end_date"] = s.end_date

	columns = sorted(windows.values(), key=lambda w: getdate(w["start_date"]))
	for col in columns:
		col["is_future"] = False

	# Extend the axis with upcoming empty windows for forward planning.
	columns += _build_future_columns(columns, future_count)

	today = getdate()
	for idx, col in enumerate(columns, start=1):
		col["seq"] = idx
		col["label"] = _("Sprint {0}").format(idx)
		col["is_current"] = bool(
			col["start_date"]
			and col["end_date"]
			and getdate(col["start_date"]) <= today <= getdate(col["end_date"])
		)

	# --- Build rows (lanes) and cells ---
	rows = {}
	cells = {}

	for s in sprints:
		if not s.start_date:
			continue

		lane_key = (s.get(group_by) or "").strip()
		if not lane_key:
			lane_key = _("(Unassigned)")

		row = rows.setdefault(
			lane_key,
			{"key": lane_key, "label": lane_key, "projects": set(), "sprint_count": 0},
		)
		row["sprint_count"] += 1
		if s.project:
			row["projects"].add(s.project)

		col_key = getdate(s.start_date).isoformat()
		cell_key = f"{lane_key}::{col_key}"

		sprint_items = items_by_sprint.get(s.name, [])
		cell = _build_cell(s, sprint_items, search_term, epic_titles)

		# Two sprints may collide in one (lane, window); keep the richer one.
		existing = cells.get(cell_key)
		if existing is None or len(cell["work_items"]) > len(existing["work_items"]):
			cells[cell_key] = cell

	# Finalise rows: turn project sets into a sorted list, sort lanes by label.
	row_list = []
	for r in rows.values():
		r["projects"] = sorted(r["projects"])
		row_list.append(r)
	row_list.sort(key=lambda r: r["label"].lower())

	return {
		"group_by": group_by,
		"columns": columns,
		"rows": row_list,
		"cells": cells,
		# Drives the "Create Missing Sprint(s)" control, which is only offered
		# under project grouping (see create_missing_sprints).
		"missing_count": _board_missing_count(sprints, group_by, future_count),
	}


# Work item types that may sit in the backlog. Epics are containers, not
# schedulable work, so they are never listed here.
BACKLOG_TYPES = ("Task", "User Story", "Bug")


@frappe.whitelist()
def get_unassigned_work_items(limit=200):
	"""Return Work Items not attached to any Sprint, newest-modified first.

	These populate the Roadmap's backlog panel so a Business Analyst can drag
	each one onto a sprint. Only schedulable types (Task / User Story / Bug)
	are listed and the order is reverse-chronological by ``modified`` — the
	last edited item shows first, per the roadmap spec.

	When a Backlog Status is configured in Frappe Agile Settings, the panel is
	further narrowed to unsprinted items in that status; left blank, unsprinted
	items of every status are shown.
	"""
	frappe.has_permission("Work Item", "read", throw=True)

	filters = {
		"sprint": ["is", "not set"],
		"work_item_type": ["in", list(BACKLOG_TYPES)],
	}

	backlog_status = frappe.db.get_single_value("Frappe Agile Settings", "backlog_status")
	if backlog_status:
		filters["status"] = backlog_status

	rows = frappe.get_list(
		"Work Item",
		filters=filters,
		fields=[
			"name",
			"title",
			"work_item_type",
			"status",
			"story_points",
			"project",
			"epic",
			"assignee_user",
			"modified",
		],
		order_by="modified desc",
		limit_page_length=cint(limit) or 0,
	)

	return [
		{
			"name": wi.name,
			"title": wi.title or wi.name,
			"type": wi.work_item_type,
			"status": wi.status,
			"story_points": flt(wi.story_points),
			"project": wi.project,
			"epic": wi.epic,
			"assignee_user": wi.assignee_user,
			"accepted": wi.status == ACCEPTED_STATUS,
			"modified": wi.modified,
		}
		for wi in rows
	]


def _board_missing_count(sprints, group_by, future_count):
	"""How many upcoming (project, window) slots on this board have no Sprint.

	Zero under any grouping other than project: Sprints cannot be created from a
	prefix lane, so there is nothing to offer.
	"""
	if group_by != "project":
		return 0

	board_projects = sorted({(s.project or "").strip() for s in sprints if (s.project or "").strip()})
	prefixes = _project_prefixes(board_projects)
	creatable = [p for p in board_projects if prefixes.get(p)]
	return len(_missing_upcoming_windows(creatable, future_count))


def _build_future_columns(existing, future_count):
	"""Project empty Wed→Tue sprint windows forward of all existing windows.

	Windows are the standard weekly cadence (Wednesday start, Tuesday end). The
	first one begins on the first sprint-start weekday after every existing
	window has ended, so generated columns never overlap real sprints — even an
	irregular (e.g. two-week) trailing sprint. Generation continues until
	`future_count` windows lie beyond today, filling any gap up to today as well.
	Capped to avoid runaway generation.
	"""
	if not existing or future_count <= 0:
		return []

	# Start strictly after the latest end_date among existing windows.
	last_end = max(getdate(c.get("end_date") or c["start_date"]) for c in existing)
	start = align_to_sprint_start(add_days(last_end, 1))

	today = getdate()
	future = []
	i = 0
	while sum(1 for f in future if getdate(f["start_date"]) > today) < future_count and i < 104:
		ws = add_days(start, 7 * i)
		future.append(
			{
				"key": ws.isoformat(),
				"start_date": ws,
				"end_date": add_days(ws, SPRINT_SPAN_DAYS),
				"is_future": True,
			}
		)
		i += 1
	return future


def _epic_titles(epic_ids):
	"""Map {epic_name: title} for the given Epic work-item ids (blank/None ignored).

	Cells group their work items under the parent Epic; the ``epic`` field only
	stores the Epic's id, so its human title is fetched here in one query.
	"""
	names = sorted({e for e in epic_ids if e})
	if not names:
		return {}
	rows = frappe.get_all(
		"Work Item",
		filters={"name": ["in", names]},
		fields=["name", "title"],
	)
	return {r.name: (r.title or r.name) for r in rows}


def _build_cell(sprint, items, search_term, epic_titles=None):
	"""Assemble a single sprint cell payload."""
	epic_titles = epic_titles or {}
	total_points = 0.0
	accepted_points = 0.0
	work_items = []

	for wi in items:
		pts = flt(wi.story_points)
		total_points += pts
		is_accepted = wi.status == ACCEPTED_STATUS
		if is_accepted:
			accepted_points += pts

		work_items.append(
			{
				"name": wi.name,
				"title": wi.title or wi.name,
				"type": wi.work_item_type,
				"status": wi.status,
				"story_points": pts,
				"epic": wi.epic,
				"epic_title": epic_titles.get(wi.epic) if wi.epic else None,
				"assignee_user": wi.assignee_user,
				"accepted": is_accepted,
			}
		)

	# Acceptance % — live from items; fall back to stored velocity if no points.
	if total_points > 0:
		acceptance_pct = round((accepted_points / total_points) * 100)
	elif flt(sprint.expected_velocity) > 0:
		acceptance_pct = round((flt(sprint.points_accepted) / flt(sprint.expected_velocity)) * 100)
	else:
		# No story points anywhere — fall back to item count completion.
		done = sum(1 for wi in items if wi.status == ACCEPTED_STATUS)
		acceptance_pct = round((done / len(items)) * 100) if items else 0

	# Apply search highlight flag (does not remove items, just marks matches).
	matched = False
	if search_term:
		matched = search_term in (sprint.name or "").lower() or any(
			search_term in (wi["title"] or "").lower() for wi in work_items
		)

	return {
		"sprint": sprint.name,
		"status": sprint.status,
		"start_date": sprint.start_date,
		"end_date": sprint.end_date,
		"sprint_goal": sprint.sprint_goal,
		"total_points": flt(total_points, 1),
		"accepted_points": flt(accepted_points, 1),
		"acceptance_pct": acceptance_pct,
		"item_count": len(work_items),
		"accepted_count": sum(1 for wi in work_items if wi["accepted"]),
		"work_items": work_items,
		"search_matched": matched,
	}


# ---------------------------------------------------------------------------
# Drag & drop: move a Work Item between sprints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def move_work_item(
	work_item,
	target_sprint=None,
	lane=None,
	group_by="sprint_prefix",
	window_start=None,
	window_end=None,
):
	"""Move a Work Item into `target_sprint`.

	If `target_sprint` is not given, an empty future slot was targeted: a Draft
	Sprint is auto-created for the (lane, window). Auto-creation is only possible
	when grouping by project — a Sprint requires a Project, and only the project
	lane identifies one. Under sprint-prefix grouping the lane is a bare prefix
	that may belong to no project at all, so the move is refused with guidance
	rather than creating an unowned Sprint.

	Saving the Work Item runs its normal `on_update`, which keeps the Sprint Work
	Item child tables in sync, marks the item as brought-forward, recalculates
	velocity, and blocks assignment into a Completed sprint.
	"""
	if not frappe.has_permission("Work Item", "write"):
		frappe.throw(_("You do not have permission to move Work Items."), frappe.PermissionError)

	created = False
	if not target_sprint:
		if group_by != "project" or not lane or not window_start:
			frappe.throw(
				_("No sprint exists for this slot. Sprints can only be created from the "
				  "Roadmap when it is grouped by Project — switch Group by to Project, "
				  "or create the Sprint first and then move the item.")
			)
		target_sprint, created = _ensure_sprint_for_window(lane, window_start, window_end)

	wi = frappe.get_doc("Work Item", work_item)
	source_sprint = wi.sprint

	if source_sprint == target_sprint:
		return {"target_sprint": target_sprint, "source_sprint": source_sprint, "created": False, "unchanged": True}

	wi.sprint = target_sprint
	wi.save()
	frappe.db.commit()

	return {
		"target_sprint": target_sprint,
		"source_sprint": source_sprint,
		"created": created,
		"title": wi.title or wi.name,
	}


def _require_creatable_project(project):
	"""Validate that Sprints can actually be created for *project*.

	Sprint.sprint_prefix is reqd, read-only and fetched from the Project, so a
	Project without one produces a bare MandatoryError on sprint_prefix that
	says nothing about the real cause. Fail with an actionable message instead.
	"""
	if not project:
		frappe.throw(_("A Project is required to create a Sprint."))

	if not frappe.db.exists("Project", project):
		frappe.throw(_("Project {0} does not exist.").format(project))

	if not frappe.db.get_value("Project", project, "custom_sprint_prefix"):
		frappe.throw(
			_(
				"Project {0} has no Sprint Prefix, so its Sprints cannot be named. "
				"Set one on the Project first."
			).format(project)
		)


def _ensure_sprint_for_window(project, window_start, window_end):
	"""Return an existing sprint for (project, window) or create one.

	Returns (sprint_name, created_bool).
	"""
	# Snap to the standard Wed→Tue window so auto-created sprints follow cadence.
	ws = align_to_sprint_start(window_start)
	we = add_days(ws, SPRINT_SPAN_DAYS)

	existing = frappe.db.get_value("Sprint", {"project": project, "start_date": ws}, "name")
	if existing:
		return existing, False

	if not frappe.has_permission("Sprint", "create"):
		frappe.throw(
			_("A new Sprint is needed for this slot, but you lack permission to create Sprints."),
			frappe.PermissionError,
		)

	_require_creatable_project(project)

	# sprint_prefix is deliberately not set: it is read-only and fetched from
	# project.custom_sprint_prefix, so setting it here would be overwritten.
	doc = frappe.get_doc(
		{
			"doctype": "Sprint",
			"project": project,
			"status": "Draft",
			"start_date": ws,
			"end_date": we,
			"sprint_goal": _("Planned via Roadmap"),
		}
	)
	doc.insert()
	return doc.name, True


def _latest_business_analyst(project):
	"""Business Analyst of the most recent sprint (by start_date) for a project."""
	rows = frappe.get_all(
		"Sprint",
		filters={"project": project, "business_analyst": ["is", "set"]},
		fields=["business_analyst"],
		order_by="start_date desc",
		limit=1,
	)
	return rows[0].business_analyst if rows else None


def _missing_upcoming_windows(projects, future_count):
	"""Return [(project, window_start, window_end)] that need a Draft sprint.

	The target for each project is the next ``future_count`` standard Wed→Tue
	windows strictly after today. A window is "missing" when no sprint of that
	project already starts on it. This is idempotent: once the target windows are
	filled, the result is empty (so the create button can hide).
	"""
	projects = [p for p in (projects or []) if p]
	if not projects or future_count <= 0:
		return []

	today = getdate()
	# First upcoming window: the standard sprint-start weekday strictly after today.
	first_start = align_to_sprint_start(add_days(today, 1))
	target_starts = [add_days(first_start, 7 * i) for i in range(future_count)]

	# One query for all existing (project, start_date) pairs in the target range.
	existing_rows = frappe.get_all(
		"Sprint",
		filters={"project": ["in", projects], "start_date": ["in", target_starts]},
		fields=["project", "start_date"],
	)
	existing = {(r.project, getdate(r.start_date)) for r in existing_rows}

	missing = []
	for project in projects:
		for ws in target_starts:
			if (project, getdate(ws)) not in existing:
				missing.append((project, ws, add_days(ws, SPRINT_SPAN_DAYS)))
	return missing


@frappe.whitelist()
def create_missing_sprints(group_by="project", lane=None, sprint_status=None, future_count=None, lanes=None):
	"""Create Draft sprints for every upcoming window that has no sprint yet.

	For each project lane shown on the board, a Draft Sprint is created for each
	upcoming window (within the Plan-ahead range) that does not already have one.
	New sprints inherit the project's latest Business Analyst.

	Args:
		lanes: optional JSON list of project names to restrict creation to.
			When given, only those projects are filled (the Business Analyst
			selected a subset of projects on the board); otherwise every project
			on the board is filled.

	Only supported when grouping by project: a Sprint requires a Project, and its
	name comes from that Project's Sprint Prefix. Returns
	{"created": [names], "created_count": n, "skipped": [{project, reason}]}.
	"""
	if group_by != "project":
		frappe.throw(
			_("Missing sprints can only be created when the Roadmap is grouped by Project, "
			  "because every Sprint must belong to a Project.")
		)

	frappe.has_permission("Sprint", "create", throw=True)

	future_count = cint(future_count) if future_count not in (None, "") else DEFAULT_FUTURE_COUNT

	projects = _board_projects(lane, sprint_status)

	# Restrict to the projects the user selected, if any. Intersecting with the
	# board projects keeps a stale/forged selection from creating off-board lanes.
	selected = _parse_lane_selection(lanes)
	if selected is not None:
		projects = [p for p in projects if p in selected]

	# A project with no Sprint Prefix cannot name its sprints. Skip it with a
	# reason rather than aborting the whole batch for the other projects.
	creatable, skipped = [], []
	prefixes = _project_prefixes(projects)
	for project in projects:
		if prefixes.get(project):
			creatable.append(project)
		else:
			skipped.append({"project": project, "reason": _("No Sprint Prefix set on the Project.")})

	missing = _missing_upcoming_windows(creatable, future_count)
	if not missing:
		return {"created": [], "created_count": 0, "skipped": skipped}

	ba_by_project = {}
	created = []
	for project, ws, we in missing:
		if project not in ba_by_project:
			ba_by_project[project] = _latest_business_analyst(project)

		# sprint_prefix is omitted on purpose — read-only, fetched from the Project.
		doc = frappe.get_doc(
			{
				"doctype": "Sprint",
				"project": project,
				"status": "Draft",
				"start_date": ws,
				"end_date": we,
				"sprint_goal": _("Planned via Roadmap"),
				"business_analyst": ba_by_project[project],
			}
		)
		doc.insert()
		created.append(doc.name)

	frappe.db.commit()
	return {"created": created, "created_count": len(created), "skipped": skipped}


def _parse_lane_selection(lanes):
	"""Normalise the client's lane selection into a set of prefixes, or None.

	Returns None when no selection was made (create for all tracks) and a set of
	trimmed, non-empty prefixes otherwise. An empty selection also returns an
	empty set so nothing is created — the caller distinguishes it from None.
	"""
	if lanes in (None, ""):
		return None
	if isinstance(lanes, str):
		lanes = frappe.parse_json(lanes)
	return {(p or "").strip() for p in (lanes or []) if (p or "").strip()}


def _board_projects(lane=None, sprint_status=None):
	"""Distinct, non-empty projects shown on the board for the filters."""
	sprint_filters = {}
	if sprint_status:
		sprint_filters["status"] = sprint_status
	if lane:
		sprint_filters["project"] = lane

	rows = frappe.get_all(
		"Sprint",
		filters=sprint_filters,
		fields=["project"],
		distinct=True,
		limit_page_length=0,
	)
	return sorted({(r.project or "").strip() for r in rows if (r.project or "").strip()})


def _project_prefixes(projects):
	"""Map {project: custom_sprint_prefix} for the given projects, in one query."""
	projects = [p for p in (projects or []) if p]
	if not projects:
		return {}

	rows = frappe.get_all(
		"Project",
		filters={"name": ["in", projects]},
		fields=["name", "custom_sprint_prefix"],
		limit_page_length=0,
	)
	return {r.name: (r.custom_sprint_prefix or "").strip() for r in rows}
