# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

"""Server-side data provider for the Roadmap board page.

The Roadmap renders a Kanban-style grid:
  - Rows    = one lane per **active SCRUM Project** — each lane runs a sequence
              of sprints over time. The row axis is always the Project; there is
              no other grouping. A project with no sprints yet still gets a lane
              so work can be planned into it.
  - Columns = weekly time windows, aligned across lanes by sprint start_date.
              The axis is extended with empty *future* windows so work can be
              planned ahead and dragged into upcoming sprints.
  - Cells   = the Sprint that falls in that (project, window), with its status,
              story-point acceptance %, and the list of work items (each shown
              with a checkbox marking whether the item is accepted / Done).

Board membership is a hard restriction the user cannot widen — Project Type
"SCRUM Project", Is Active "Yes", and Show in Roadmap "Yes" (one_fm's
`custom_show_in_roadmap`, WI-002045). A SCRUM project is therefore off the board
until someone opts it in; blank does not count as Yes.

Within that set the user narrows with a single multi-select **Projects** filter
offering the three Project statuses (Open / Completed / Cancelled) followed by
the projects themselves. The two halves arrive as separate arguments
(`project_status` and `lane`) and AND together; leaving either empty means "no
restriction on that axis". Ticking statuses also narrows which projects the
filter lists, so the two halves stay consistent with each other.

Acceptance is computed live from the work items rather than from the stored
`points_accepted` field so the board is always accurate even if that cached
field is stale.

Work items can be moved between sprints via `move_work_item` (drag & drop on
the client). Dropping into an empty future slot auto-creates a Draft Sprint for
that project/window, named from the project's Sprint Prefix.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate

# A work item is considered "accepted" when it reaches this status.
ACCEPTED_STATUS = "Done"

# Default number of empty future sprint windows to project forward for planning.
DEFAULT_FUTURE_COUNT = 8

# Only projects of this type, and only while they are active, appear on the board.
SCRUM_PROJECT_TYPE = "SCRUM Project"

# On top of that, a project has to be opted in. The flag is one_fm's Project
# custom field "Show in Roadmap" (WI-002045), a Select of blank / Yes / No: only
# "Yes" earns a lane, so a project stays off the board until someone puts it
# there. Blank is not treated as Yes — an uncurated project is not on the board.
ROADMAP_FLAG_FIELD = "custom_show_in_roadmap"
ROADMAP_FLAG_ON = "Yes"

# The Project statuses the multi-select filter may narrow the board to.
PROJECT_STATUSES = ("Open", "Completed", "Cancelled")

# Sprints run Wednesday → Tuesday (7-day window). The cadence helpers live on the
# Sprint controller so the board and the doctype stay in lock-step.
from frappe_agile.frappe_agile.doctype.sprint.sprint import (  # noqa: E402
	SPRINT_SPAN_DAYS,
	SPRINT_START_WEEKDAY,
	align_to_sprint_start,
)


@frappe.whitelist()
def get_roadmap_data(project_status=None, lane=None, sprint_status=None, search=None, future_count=None):
	"""Return the full roadmap grid, one row per active SCRUM Project.

	Args:
		project_status: optional multi-select of Project statuses (list or JSON
			list of "Open" / "Completed" / "Cancelled"). Empty = every status.
		lane: optional, restrict to these Projects — a single name, a list, or a
			JSON list. Empty = every project on the board.
		sprint_status: optional, restrict to sprints in this status.
		search: optional, free-text filter on work item title / sprint name.
		future_count: how many empty future sprint windows to append for planning.

	Returns dict: {columns: [...], rows: [...], cells: {cell_key: {...}}}
	"""
	frappe.has_permission("Sprint", "read", throw=True)
	frappe.has_permission("Work Item", "read", throw=True)

	future_count = cint(future_count) if future_count not in (None, "") else DEFAULT_FUTURE_COUNT

	# The row axis is the project list, not the sprint list — a brand-new project
	# with no sprints must still get a lane to plan into.
	projects = _scrum_projects(project_status=project_status, lane=lane)
	if not projects:
		return {"columns": [], "rows": [], "cells": {}, "missing_count": 0}

	project_names = [p.name for p in projects]

	sprint_filters = {"project": ["in", project_names]}
	if sprint_status:
		sprint_filters["status"] = sprint_status

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

	# --- Fetch all work items for these sprints in one query ---
	sprint_names = [s.name for s in sprints]
	work_items = (
		frappe.get_list(
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
		if sprint_names
		else []
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

	# --- Build rows (one per project, in project order) and cells ---
	rows = {}
	row_list = []
	for p in projects:
		row = {
			"key": p.name,
			"label": p.project_name or p.name,
			"prefix": (p.custom_sprint_prefix or "").strip(),
			"project_status": p.status,
			"sprint_count": 0,
		}
		rows[p.name] = row
		row_list.append(row)

	cells = {}
	for s in sprints:
		if not s.start_date:
			continue

		row = rows.get(s.project)
		if row is None:
			# Shouldn't happen — sprints were queried for these projects only.
			continue
		row["sprint_count"] += 1

		col_key = getdate(s.start_date).isoformat()
		cell_key = f"{s.project}::{col_key}"

		sprint_items = items_by_sprint.get(s.name, [])
		cell = _build_cell(s, sprint_items, search_term, epic_titles)

		# Two sprints may collide in one (project, window); keep the richer one.
		existing = cells.get(cell_key)
		if existing is None or len(cell["work_items"]) > len(existing["work_items"]):
			cells[cell_key] = cell

	# How many upcoming windows still need a sprint — drives the "Create Missing
	# Sprints" button. Computed the same way as the creator so the count converges
	# to zero once they are created.
	missing_count = len(_missing_upcoming_windows(projects, future_count))

	return {
		"columns": columns,
		"rows": row_list,
		"cells": cells,
		"missing_count": missing_count,
	}


# Two of the backlog's three tests are fixed: an item on a sprint is scheduled
# rather than backlog, and an Epic is a container rather than schedulable work.
# The third — which statuses count as "not started yet" — defaults to these and
# can be overridden through Backlog Status on Frappe Agile Settings.
EXCLUDED_BACKLOG_TYPE = "Epic"
DEFAULT_BACKLOG_STATUSES = ("Draft", "Open")


def get_backlog_statuses():
	"""The Work Item statuses the backlog panel lists.

	Backlog Status on Frappe Agile Settings replaces the default when it is set —
	one status, or several separated by commas. Left blank, the default stands.
	"""
	configured = frappe.db.get_single_value("Frappe Agile Settings", "backlog_status") or ""
	statuses = [status.strip() for status in configured.split(",") if status.strip()]
	return statuses or list(DEFAULT_BACKLOG_STATUSES)


@frappe.whitelist()
def get_unassigned_work_items(limit=200):
	"""Return Work Items not attached to any Sprint, newest-modified first.

	These populate the Roadmap's backlog panel so a Business Analyst can drag
	each one onto a sprint. By default the panel lists unsprinted Work Items that
	are still Draft or Open and are not Epics; Backlog Status on Frappe Agile
	Settings can put a different set of statuses in place of Draft and Open. The
	order is reverse-chronological by ``modified`` — the last edited item shows
	first, per the roadmap spec.
	"""
	frappe.has_permission("Work Item", "read", throw=True)

	filters = {
		"sprint": ["is", "not set"],
		"work_item_type": ["!=", EXCLUDED_BACKLOG_TYPE],
		"status": ["in", get_backlog_statuses()],
	}

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


@frappe.whitelist()
def get_scrum_projects():
	"""The active SCRUM Projects the current user may read — the board's lanes.

	Feeds the client's Projects filter, which lists these below the three Project
	statuses. Deliberately the same source as the board rows, so what can be
	picked and what can be shown never drift apart.
	"""
	return [
		{"name": p.name, "label": p.project_name or p.name, "status": p.status}
		for p in _scrum_projects()
	]


def _scrum_projects(project_status=None, lane=None):
	"""Active SCRUM Projects the current user may read, in display order.

	These are the Roadmap's rows. Membership of the board is fixed and not
	user-controllable: Project Type "SCRUM Project", Is Active "Yes", and Show in
	Roadmap "Yes". `project_status` and `lane` are the two halves of the
	user-facing Projects multi-select narrowing that set further — by status and
	by named project respectively. They AND together.
	`frappe.get_list` keeps the result permission-scoped.
	"""
	frappe.has_permission("Project", "read", throw=True)

	filters = {
		"project_type": SCRUM_PROJECT_TYPE,
		"is_active": "Yes",
		ROADMAP_FLAG_FIELD: ROADMAP_FLAG_ON,
	}

	statuses = _parse_status_selection(project_status)
	if statuses:
		filters["status"] = ["in", statuses]

	lanes = _parse_lane_filter(lane)
	if lanes:
		filters["name"] = ["in", lanes]

	return frappe.get_list(
		"Project",
		filters=filters,
		fields=["name", "project_name", "status", "custom_sprint_prefix"],
		order_by="project_name asc, name asc",
		limit_page_length=0,
	)


def _parse_lane_filter(lane):
	"""Normalise the Projects half of the filter into a list of names, or None.

	Accepts a single project name, a list, or a JSON-encoded list. Empty in every
	form returns None, meaning "no restriction" — unlike `_parse_lane_selection`,
	where an empty selection deliberately means "nothing". Names the user may not
	read are dropped by `frappe.get_list`, so no validation is needed here.
	"""
	if lane in (None, ""):
		return None
	if isinstance(lane, str):
		lane = lane.strip()
		lane = frappe.parse_json(lane) if lane.startswith("[") else [lane]
	names = [n for n in ((p or "").strip() for p in (lane or [])) if n]
	return names or None


def _parse_status_selection(project_status):
	"""Normalise the Project Status multi-select into a list of known statuses.

	Accepts a list, a JSON-encoded list, or a single status string. Unknown
	values are dropped so a forged filter can never widen the query beyond the
	three Project statuses.
	"""
	if project_status in (None, ""):
		return []
	if isinstance(project_status, str):
		project_status = project_status.strip()
		if project_status.startswith("["):
			project_status = frappe.parse_json(project_status)
		else:
			project_status = [project_status]
	return [s for s in {(v or "").strip() for v in project_status} if s in PROJECT_STATUSES]


def _current_window_start(reference_date=None):
	"""Start (Wednesday) of the standard sprint window containing *reference_date*."""
	d = getdate(reference_date or getdate())
	return add_days(d, -((d.weekday() - SPRINT_START_WEEKDAY) % 7))


def _build_future_columns(existing, future_count):
	"""Project empty Wed→Tue sprint windows forward of all existing windows.

	Windows are the standard weekly cadence (Wednesday start, Tuesday end). The
	first one begins on the first sprint-start weekday after every existing
	window has ended, so generated columns never overlap real sprints — even an
	irregular (e.g. two-week) trailing sprint. Generation continues until
	`future_count` windows lie beyond today, filling any gap up to today as well.
	Capped to avoid runaway generation.

	With no existing windows at all (every shown project is sprint-less) the axis
	is seeded from the *current* window, so the board still renders a usable
	timeline to plan the first sprints into.
	"""
	if future_count <= 0:
		return []

	if existing:
		# Start strictly after the latest end_date among existing windows.
		last_end = max(getdate(c.get("end_date") or c["start_date"]) for c in existing)
		start = align_to_sprint_start(add_days(last_end, 1))
	else:
		start = _current_window_start()

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
				# The two independent flags a cell shows: the checkbox is
				# assignment, the strikethrough is completion.
				"assigned": bool(wi.assignee_user),
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
		"assigned_count": sum(1 for wi in work_items if wi["assigned"]),
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
	window_start=None,
	window_end=None,
):
	"""Move a Work Item into `target_sprint`.

	If `target_sprint` is not given, an empty future slot was targeted: a Draft
	Sprint is auto-created for the (project, window). `lane` is the project; the
	new Sprint is named from that project's Sprint Prefix, so a project without
	one cannot be planned into until the prefix is set.

	Saving the Work Item runs its normal `on_update`, which keeps the Sprint Work
	Item child tables in sync, marks the item as brought-forward, recalculates
	velocity, and blocks assignment into a Completed sprint.
	"""
	if not frappe.has_permission("Work Item", "write"):
		frappe.throw(_("You do not have permission to move Work Items."), frappe.PermissionError)

	created = False
	if not target_sprint:
		if not lane or not window_start:
			frappe.throw(
				_("No sprint exists for this slot and one cannot be auto-created here. "
				  "Create a Sprint first, then move the item.")
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


def _ensure_sprint_for_window(project, window_start, window_end):
	"""Return an existing sprint for (project, window) or create a Draft one.

	Returns (sprint_name, created_bool).
	"""
	# Snap to the standard Wed→Tue window so auto-created sprints follow cadence.
	ws = align_to_sprint_start(window_start)
	we = add_days(ws, SPRINT_SPAN_DAYS)

	existing = frappe.db.get_value("Sprint", {"project": project, "start_date": ws}, "name")
	if existing:
		return existing, False

	prefix = _sprint_prefix_for_project(project)

	if not frappe.has_permission("Sprint", "create"):
		frappe.throw(
			_("A new Sprint is needed for this slot, but you lack permission to create Sprints."),
			frappe.PermissionError,
		)

	doc = frappe.get_doc(
		{
			"doctype": "Sprint",
			"project": project,
			"sprint_prefix": prefix,
			"status": "Draft",
			"start_date": ws,
			"end_date": we,
			"sprint_goal": _("Planned via Roadmap"),
			"business_analyst": _latest_business_analyst(project),
		}
	)
	doc.insert()
	return doc.name, True


def _sprint_prefix_for_project(project):
	"""Sprint Prefix of a project that belongs on the board, or throw saying why not.

	Re-checks board membership rather than trusting the caller: `lane` arrives from
	the client, so a project that has no lane must not be plannable by naming it
	in a request.
	"""
	row = frappe.db.get_value(
		"Project",
		project,
		["project_type", "is_active", "custom_sprint_prefix", ROADMAP_FLAG_FIELD],
		as_dict=True,
	)
	if (
		not row
		or row.project_type != SCRUM_PROJECT_TYPE
		or row.is_active != "Yes"
		or row.get(ROADMAP_FLAG_FIELD) != ROADMAP_FLAG_ON
	):
		frappe.throw(
			_("{0} is not an active SCRUM Project shown in the Roadmap, so sprints cannot be planned for it here.").format(
				project
			)
		)

	prefix = (row.custom_sprint_prefix or "").strip()
	if not prefix:
		frappe.throw(
			_("Project {0} has no Sprint Prefix — set one on the Project before planning sprints for it.").format(
				project
			)
		)
	return prefix


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
	"""Return [(project, prefix, window_start, window_end)] needing a Draft sprint.

	The target for each project is the next ``future_count`` standard Wed→Tue
	windows strictly after today. A window is "missing" when no sprint of that
	project already starts on it. Projects without a Sprint Prefix are skipped —
	there would be nothing to name the sprint from. This is idempotent: once the
	target windows are filled, the result is empty (so the create button hides).
	"""
	planned = [
		(p["name"], (p.get("custom_sprint_prefix") or "").strip())
		for p in (projects or [])
		if (p.get("custom_sprint_prefix") or "").strip()
	]
	if not planned or future_count <= 0:
		return []

	today = getdate()
	# First upcoming window: the standard sprint-start weekday strictly after today.
	first_start = align_to_sprint_start(add_days(today, 1))
	target_starts = [add_days(first_start, 7 * i) for i in range(future_count)]

	# One query for all existing (project, start_date) pairs in the target range.
	existing_rows = frappe.get_all(
		"Sprint",
		filters={"project": ["in", [n for n, _p in planned]], "start_date": ["in", target_starts]},
		fields=["project", "start_date"],
	)
	existing = {(r.project, getdate(r.start_date)) for r in existing_rows}

	missing = []
	for name, prefix in planned:
		for ws in target_starts:
			if (name, getdate(ws)) not in existing:
				missing.append((name, prefix, ws, add_days(ws, SPRINT_SPAN_DAYS)))
	return missing


@frappe.whitelist()
def create_missing_sprints(project_status=None, lane=None, future_count=None, lanes=None):
	"""Create Draft sprints for every upcoming window that has no sprint yet.

	For each project lane shown on the board, a Draft Sprint is created for each
	upcoming window (within the Plan-ahead range) that does not already have one.
	New sprints are named from the project's Sprint Prefix and inherit that
	project's latest Business Analyst.

	Args:
		lane: the board's Projects filter — which projects are on screen at all.
		lanes: optional JSON list of Projects to restrict creation to. When
			given, only those projects are filled (the Business Analyst selected
			a subset on the board); otherwise every project on the board is.

	Returns {"created": [names], "created_count": n}.
	"""
	frappe.has_permission("Sprint", "create", throw=True)

	future_count = cint(future_count) if future_count not in (None, "") else DEFAULT_FUTURE_COUNT

	projects = _scrum_projects(project_status=project_status, lane=lane)

	# Restrict to the projects the user selected, if any. Intersecting with the
	# board projects keeps a stale/forged selection from creating off-board sprints.
	selected = _parse_lane_selection(lanes)
	if selected is not None:
		projects = [p for p in projects if p.name in selected]

	missing = _missing_upcoming_windows(projects, future_count)
	if not missing:
		return {"created": [], "created_count": 0}

	ba_by_project = {}
	created = []
	for project, prefix, ws, we in missing:
		if project not in ba_by_project:
			ba_by_project[project] = _latest_business_analyst(project)

		doc = frappe.get_doc(
			{
				"doctype": "Sprint",
				"project": project,
				"sprint_prefix": prefix,
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
	return {"created": created, "created_count": len(created)}


def _parse_lane_selection(lanes):
	"""Normalise the client's lane selection into a set of projects, or None.

	Returns None when no selection was made (create for every project) and a set
	of trimmed, non-empty project names otherwise. An empty selection also
	returns an empty set so nothing is created — the caller distinguishes it
	from None.
	"""
	if lanes in (None, ""):
		return None
	if isinstance(lanes, str):
		lanes = frappe.parse_json(lanes)
	return {(p or "").strip() for p in (lanes or []) if (p or "").strip()}
