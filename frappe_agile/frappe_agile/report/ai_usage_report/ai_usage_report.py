# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt


def execute(filters=None):
	if not filters:
		filters = {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"fieldname": "combined_labels", "label": "Combined Labels", "fieldtype": "Data", "width": 300},
		{"fieldname": "story_count", "label": "Story Count", "fieldtype": "Int", "width": 120},
		{"fieldname": "story_count_pct", "label": "Story Count %", "fieldtype": "Percent", "width": 130},
		{"fieldname": "story_points", "label": "Story Points", "fieldtype": "Float", "width": 130},
		{"fieldname": "story_points_pct", "label": "Story Points %", "fieldtype": "Percent", "width": 140},
	]


def get_data(filters):
	if not filters:
		filters = {}

	# ------------------------------------------------------------------
	# 1. Resolve sprints matching the date range / sprint filter
	# ------------------------------------------------------------------
	Sprint = frappe.qb.DocType("Sprint")
	sprint_query = (
		frappe.qb.from_(Sprint)
		.select(Sprint.name)
	)

	if filters.get("start_date") and filters.get("end_date"):
		sprint_query = sprint_query.where(Sprint.start_date <= filters.get("end_date"))
		sprint_query = sprint_query.where(Sprint.end_date >= filters.get("start_date"))

	if filters.get("sprint"):
		sprint_query = sprint_query.where(Sprint.name == filters.get("sprint"))

	sprint_rows = sprint_query.run(as_dict=True)
	if not sprint_rows:
		return []

	sprint_names = [s.name for s in sprint_rows]

	# ------------------------------------------------------------------
	# 2. Fetch Work Items (User Story and Task) linked to those sprints
	# ------------------------------------------------------------------
	WorkItem = frappe.qb.DocType("Work Item")
	wi_rows = (
		frappe.qb.from_(WorkItem)
		.select(WorkItem.name, WorkItem.story_points)
		.where(WorkItem.sprint.isin(sprint_names))
		.where(WorkItem.work_item_type.isin(["User Story", "Task"]))
	).run(as_dict=True)

	if not wi_rows:
		return []

	wi_names = [w.name for w in wi_rows]
	wi_points_map = {w.name: flt(w.story_points) for w in wi_rows}

	# ------------------------------------------------------------------
	# 3. Fetch all Work Item Label rows for those work items
	# ------------------------------------------------------------------
	WILabel = frappe.qb.DocType("Work Item Label")
	label_rows = (
		frappe.qb.from_(WILabel)
		.select(WILabel.parent, WILabel.label)
		.where(WILabel.parent.isin(wi_names))
	).run(as_dict=True)

	# ------------------------------------------------------------------
	# 4. Build label combination per work item
	# ------------------------------------------------------------------
	# wi_name -> sorted list of labels
	wi_label_map = {}
	for row in label_rows:
		wi_label_map.setdefault(row.parent, []).append(row.label)

	# Sort each WI's labels alphabetically for consistent grouping key
	wi_combo_map = {}
	for wi_name, labels in wi_label_map.items():
		combo = ", ".join(sorted(labels))
		wi_combo_map[wi_name] = combo

	# Work items with no labels get grouped as "(No Labels)"
	for wi_name in wi_names:
		if wi_name not in wi_combo_map:
			wi_combo_map[wi_name] = "(No Labels)"

	# ------------------------------------------------------------------
	# 5. Aggregate by label combination
	# ------------------------------------------------------------------
	combo_data = {}
	for wi_name, combo in wi_combo_map.items():
		if combo not in combo_data:
			combo_data[combo] = {"story_count": 0, "story_points": 0.0}
		combo_data[combo]["story_count"] += 1
		combo_data[combo]["story_points"] += wi_points_map.get(wi_name, 0.0)

	# ------------------------------------------------------------------
	# 6. Compute totals and build rows
	# ------------------------------------------------------------------
	total_stories = sum(v["story_count"] for v in combo_data.values())
	total_points = sum(v["story_points"] for v in combo_data.values())

	data = []
	for combo, metrics in combo_data.items():
		count = metrics["story_count"]
		points = flt(metrics["story_points"], 1)
		data.append({
			"combined_labels": combo,
			"story_count": count,
			"story_count_pct": flt((count / total_stories * 100) if total_stories else 0, 2),
			"story_points": points,
			"story_points_pct": flt((points / total_points * 100) if total_points else 0, 2),
		})

	# Sort by story count descending, then alphabetically by label combo
	data.sort(key=lambda x: (-x["story_count"], x["combined_labels"]))
	return data
