# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

"""Server-side data provider for the Roadmap board page.

The Roadmap renders a Kanban-style grid:
  - Rows    = a "lane" (sprint prefix, or linked Project) — each lane runs a
              sequence of sprints over time.
  - Columns = weekly time windows, aligned across lanes by sprint start_date.
  - Cells   = the Sprint that falls in that (lane, window), with its status,
              story-point acceptance %, and the list of work items (each shown
              with a checkbox marking whether the item is accepted / Done).

Acceptance is computed live from the work items rather than from the stored
`points_accepted` field so the board is always accurate even if that cached
field is stale.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

# A work item is considered "accepted" when it reaches this status.
ACCEPTED_STATUS = "Done"


@frappe.whitelist()
def get_roadmap_data(group_by="sprint_prefix", lane=None, sprint_status=None, search=None):
	"""Return the full roadmap grid.

	Args:
		group_by: "sprint_prefix" (default) or "project" — controls the row axis.
		lane: optional, restrict to a single lane (prefix or project value).
		sprint_status: optional, restrict to sprints in this status.
		search: optional, free-text filter on work item title / sprint name.

	Returns dict: {columns: [...], rows: [...], cells: {cell_key: {...}}}
	"""
	if group_by not in ("sprint_prefix", "project"):
		group_by = "sprint_prefix"

	sprint_filters = {}
	if sprint_status:
		sprint_filters["status"] = sprint_status
	if lane:
		sprint_filters[group_by] = lane

	sprints = frappe.get_all(
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
	work_items = frappe.get_all(
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
		cell = _build_cell(s, sprint_items, search_term)

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
	}


def _build_cell(sprint, items, search_term):
	"""Assemble a single sprint cell payload."""
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
