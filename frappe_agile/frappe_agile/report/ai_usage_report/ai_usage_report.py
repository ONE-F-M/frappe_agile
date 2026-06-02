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
		{"fieldname": "ai_tools_feedback", "label": "AI Tools Feedback", "fieldtype": "Data", "width": 400},
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

	# Server-side guard: require date range when no explicit sprint is given
	if not filters.get("sprint") and (
		not filters.get("start_date") or not filters.get("end_date")
	):
		return []

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
	SWI = frappe.qb.DocType("Sprint Work Item")
	wi_rows = (
		frappe.qb.from_(SWI)
		.select(SWI.work_item.as_("name"), SWI.story_points)
		.where(SWI.parent.isin(sprint_names))
		.where(SWI.parenttype == "Sprint")
		.where(SWI.work_item_type.isin(["User Story", "Task"]))
	).run(as_dict=True)

	if not wi_rows:
		return []

	wi_names = [w.name for w in wi_rows]
	wi_points_map = {w.name: flt(w.story_points) for w in wi_rows}

	# ------------------------------------------------------------------
	# 3. Fetch ai_tools_feedback from the Work Item doctype
	# ------------------------------------------------------------------
	WI = frappe.qb.DocType("Work Item")
	feedback_rows = (
		frappe.qb.from_(WI)
		.select(WI.name, WI.ai_tools_feedback)
		.where(WI.name.isin(wi_names))
	).run(as_dict=True)

	wi_feedback_map = {}
	for row in feedback_rows:
		if row.ai_tools_feedback and row.ai_tools_feedback.strip():
			wi_feedback_map[row.name] = row.ai_tools_feedback.strip()

	# ------------------------------------------------------------------
	# 4. Fetch all Work Item Label rows for those work items
	# ------------------------------------------------------------------
	WILabel = frappe.qb.DocType("Work Item Label")
	label_rows = (
		frappe.qb.from_(WILabel)
		.select(WILabel.parent, WILabel.label)
		.where(WILabel.parent.isin(wi_names))
	).run(as_dict=True)

	# ------------------------------------------------------------------
	# 5. Build label combination per work item
	# ------------------------------------------------------------------
	# wi_name -> sorted list of labels
	wi_label_map = {}
	for row in label_rows:
		wi_label_map.setdefault(row.parent, []).append(row.label)

	# Sort each WI's labels alphabetically for consistent grouping key
	# Deduplicate first to prevent "OpenAI, OpenAI" style keys from duplicate rows
	wi_combo_map = {}
	for wi_name, labels in wi_label_map.items():
		combo = ", ".join(sorted(set(labels)))
		wi_combo_map[wi_name] = combo

	# Work items with no labels get grouped as "(No Labels)"
	for wi_name in wi_names:
		if wi_name not in wi_combo_map:
			wi_combo_map[wi_name] = "(No Labels)"

	# ------------------------------------------------------------------
	# 6. Aggregate by label combination
	# ------------------------------------------------------------------
	combo_data = {}
	for wi_name, combo in wi_combo_map.items():
		if combo not in combo_data:
			combo_data[combo] = {"story_count": 0, "story_points": 0.0, "feedbacks": []}
		combo_data[combo]["story_count"] += 1
		combo_data[combo]["story_points"] += wi_points_map.get(wi_name, 0.0)

		feedback = wi_feedback_map.get(wi_name)
		if feedback:
			combo_data[combo]["feedbacks"].append(feedback)

	# ------------------------------------------------------------------
	# 7. Compute totals and build rows
	# ------------------------------------------------------------------
	total_stories = sum(v["story_count"] for v in combo_data.values())
	total_points = sum(v["story_points"] for v in combo_data.values())

	data = []
	for combo, metrics in combo_data.items():
		count = metrics["story_count"]
		points_raw = metrics["story_points"]
		points = flt(points_raw, 1)
		combined_feedback = "\n---\n".join(metrics.get("feedbacks", []))
		data.append({
			"combined_labels": combo,
			"story_count": count,
			"story_count_pct": flt((count / total_stories * 100) if total_stories else 0, 2),
			"story_points": points,
			# Use raw unrounded value for percentage to avoid compounding rounding error
			"story_points_pct": flt((points_raw / total_points * 100) if total_points else 0, 2),
			"ai_tools_feedback": combined_feedback,
		})

	# Sort by story count descending, then alphabetically by label combo
	data.sort(key=lambda x: (-x["story_count"], x["combined_labels"]))
	return data
