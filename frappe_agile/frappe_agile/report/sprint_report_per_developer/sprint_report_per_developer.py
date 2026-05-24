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
		{"fieldname": "developer", "label": "Developer", "fieldtype": "Data", "width": 180},
		{"fieldname": "sprints", "label": "Sprint(s)", "fieldtype": "Data", "width": 200},
		{"fieldname": "sprint_start_date", "label": "Sprint Start Date", "fieldtype": "Date", "width": 150},
		{"fieldname": "sprint_end_date", "label": "Sprint End Date", "fieldtype": "Date", "width": 150},
		{"fieldname": "no_of_sprints", "label": "No. of Sprints", "fieldtype": "Int", "width": 120},
		{"fieldname": "target_points", "label": "Target Points", "fieldtype": "Float", "width": 130},
		{"fieldname": "completed_points", "label": "Completed Points", "fieldtype": "Float", "width": 150},
		{"fieldname": "accepted_points", "label": "Accepted Points", "fieldtype": "Float", "width": 150},
		{"fieldname": "completion_rate", "label": "Completion Rate %", "fieldtype": "Percent", "width": 150},
		{"fieldname": "acceptance_rate", "label": "Acceptance Rate %", "fieldtype": "Percent", "width": 150},
	]


def get_data(filters):
	if not filters:
		filters = {}

	# ------------------------------------------------------------------
	# 1. Fetch matching sprints based on date range / sprint filter
	# ------------------------------------------------------------------
	Sprint = frappe.qb.DocType("Sprint")
	query = (
		frappe.qb.from_(Sprint)
		.select(Sprint.name, Sprint.start_date, Sprint.end_date)
		.orderby(Sprint.start_date, order=frappe.qb.desc)
	)

	if filters.get("start_date") and filters.get("end_date"):
		query = query.where(Sprint.start_date <= filters.get("end_date"))
		query = query.where(Sprint.end_date >= filters.get("start_date"))

	if filters.get("sprint"):
		query = query.where(Sprint.name == filters.get("sprint"))

	sprints = query.run(as_dict=True)
	if not sprints:
		return []

	sprint_names = [s.name for s in sprints]
	sprint_map = {s.name: s for s in sprints}

	# ------------------------------------------------------------------
	# 2. Fetch work items (User Story and Task only) from those sprints
	# ------------------------------------------------------------------
	SprintItem = frappe.qb.DocType("Sprint Work Item")
	wi_query = (
		frappe.qb.from_(SprintItem)
		.select(
			SprintItem.parent.as_("sprint"),
			SprintItem.assignee_user,
			SprintItem.story_points,
			SprintItem.status,
		)
		.where(SprintItem.parent.isin(sprint_names))
		.where(SprintItem.work_item_type.isin(["User Story", "Task"]))
	)
	work_items = wi_query.run(as_dict=True)

	# ------------------------------------------------------------------
	# 3. Developer velocity from settings
	# ------------------------------------------------------------------
	developer_velocity = flt(frappe.db.get_single_value("Frappe Agile Settings", "developer_velocity"))

	# ------------------------------------------------------------------
	# 4. Aggregate per (developer, sprint)
	# ------------------------------------------------------------------
	# developer -> { sprint -> {completed, accepted, total} }
	dev_sprint_data = {}

	for wi in work_items:
		user = wi.assignee_user
		if not user:
			continue

		# Apply developer filter if set
		if filters.get("developer") and user != filters.get("developer"):
			continue

		sprint_name = wi.sprint
		if user not in dev_sprint_data:
			dev_sprint_data[user] = {}
		if sprint_name not in dev_sprint_data[user]:
			dev_sprint_data[user][sprint_name] = {
				"completed_points": 0.0,
				"accepted_points": 0.0,
			}

		points = flt(wi.story_points)

		if wi.status in ("Done", "In Staging", "Rejected"):
			dev_sprint_data[user][sprint_name]["completed_points"] += points

		if wi.status == "Done":
			dev_sprint_data[user][sprint_name]["accepted_points"] += points

	if not dev_sprint_data:
		return []

	# ------------------------------------------------------------------
	# 5. Fetch user full names
	# ------------------------------------------------------------------
	all_users = list(dev_sprint_data.keys())
	users_data = frappe.get_all("User",
		filters={"name": ["in", all_users]},
		fields=["name", "full_name"]
	)
	user_full_name_map = {u.name: u.full_name or u.name for u in users_data}

	# ------------------------------------------------------------------
	# 6. Build one row per developer (aggregated across all sprints)
	# ------------------------------------------------------------------
	data = []

	for user, sprint_dict in dev_sprint_data.items():
		sprint_names_for_dev = list(sprint_dict.keys())
		no_of_sprints = len(sprint_names_for_dev)

		# Target Points = developer_velocity × number of sprints for this developer
		target_points = flt(developer_velocity * no_of_sprints, 1)

		# Sum completed and accepted across all sprints
		total_completed = flt(sum(v["completed_points"] for v in sprint_dict.values()), 1)
		total_accepted = flt(sum(v["accepted_points"] for v in sprint_dict.values()), 1)

		# Rate denominators use target_points
		completion_rate = (total_completed / target_points * 100) if target_points else 0.0
		acceptance_rate = (total_accepted / target_points * 100) if target_points else 0.0

		# Date range across all sprints for this developer
		sprint_docs = [sprint_map[s] for s in sprint_names_for_dev if s in sprint_map]
		earliest_start = min((s.start_date for s in sprint_docs if s.start_date), default=None)
		latest_end = max((s.end_date for s in sprint_docs if s.end_date), default=None)

		# Comma-separated sprint names (sorted by start date)
		sorted_sprints = sorted(sprint_docs, key=lambda s: s.start_date or "")
		sprint_label = ", ".join(s.name for s in sorted_sprints)

		data.append({
			"developer": user_full_name_map.get(user, user),
			"sprints": sprint_label,
			"sprint_start_date": earliest_start,
			"sprint_end_date": latest_end,
			"no_of_sprints": no_of_sprints,
			"target_points": target_points,
			"completed_points": total_completed,
			"accepted_points": total_accepted,
			"completion_rate": flt(completion_rate, 2),
			"acceptance_rate": flt(acceptance_rate, 2),
		})

	# Sort by developer name
	data.sort(key=lambda x: x.get("developer") or "")
	return data
