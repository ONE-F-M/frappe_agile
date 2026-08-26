# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt

from frappe_agile.frappe_agile.report.proration import get_employee_map, get_proration


def execute(filters=None):
	if not filters:
		filters = {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"fieldname": "developer", "label": "Developer", "fieldtype": "Data", "width": 180},
		{"fieldname": "sprints", "label": "Sprint(s)", "fieldtype": "HTML", "width": 200},
		{"fieldname": "sprint_start_date", "label": "Sprint Start Date", "fieldtype": "Date", "width": 150},
		{"fieldname": "sprint_end_date", "label": "Sprint End Date", "fieldtype": "Date", "width": 150},
		{"fieldname": "no_of_sprints", "label": "No. of Sprints", "fieldtype": "Int", "width": 120},
		{"fieldname": "working_days", "label": "Working Days", "fieldtype": "Int", "width": 120},
		{"fieldname": "public_holidays", "label": "Public Holidays", "fieldtype": "Int", "width": 130},
		{"fieldname": "leave_days", "label": "Leave Days", "fieldtype": "Float", "width": 120},
		{"fieldname": "target_points", "label": "Target Points", "fieldtype": "Float", "width": 130},
		{"fieldname": "points_scoped", "label": "Points Scoped", "fieldtype": "Float", "width": 130},
		{"fieldname": "percentage_target", "label": "Percentage Target %", "fieldtype": "Percent", "width": 160},
		{"fieldname": "accepted_points", "label": "Accepted Points", "fieldtype": "Float", "width": 140},
		{"fieldname": "rejected_points", "label": "Rejected Points", "fieldtype": "Float", "width": 140},
		{"fieldname": "spillover_points", "label": "Spillover Points", "fieldtype": "Float", "width": 140},
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
	# developer -> { sprint -> {scoped, accepted, rejected} }
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
				"scoped_points": 0.0,
				"accepted_points": 0.0,
				"rejected_points": 0.0,
			}

		points = flt(wi.story_points)

		# All work items in the sprint contribute to scoped points
		dev_sprint_data[user][sprint_name]["scoped_points"] += points

		if wi.status == "Done":
			dev_sprint_data[user][sprint_name]["accepted_points"] += points

		if wi.status == "Rejected":
			dev_sprint_data[user][sprint_name]["rejected_points"] += points

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

	# Map developers to their Employee record so leave can be looked up
	employee_map = get_employee_map(all_users)

	# ------------------------------------------------------------------
	# 6. Build one row per developer (aggregated across all sprints)
	# ------------------------------------------------------------------
	data = []

	for user, sprint_dict in dev_sprint_data.items():
		sprint_names_for_dev = list(sprint_dict.keys())

		# Count distinct sprint periods — sprints sharing the same (start_date, end_date) count as 1
		unique_periods = set()
		for s in sprint_names_for_dev:
			if s in sprint_map:
				unique_periods.add((sprint_map[s].start_date, sprint_map[s].end_date))
		no_of_sprints = len(unique_periods)

		# Target Points = the developer's expected velocity, prorated by the days
		# they could actually work in each distinct sprint period and summed
		# across them:
		#   velocity × (working_days − public_holidays − leave_days) / working_days
		employee = employee_map.get(user)
		factor, working_days, public_holidays, leave_days = get_proration(employee, unique_periods)
		prorated_target = developer_velocity * factor

		target_points = flt(prorated_target, 1)

		# Sum scoped, accepted, and rejected across all sprints
		total_scoped_raw = sum(v["scoped_points"] for v in sprint_dict.values())
		total_accepted_raw = sum(v["accepted_points"] for v in sprint_dict.values())
		total_rejected_raw = sum(v["rejected_points"] for v in sprint_dict.values())

		# Acceptance Rate = (Accepted Points / Points Scoped) × 100
		acceptance_rate = (total_accepted_raw / total_scoped_raw * 100) if total_scoped_raw else 0.0

		# Spillover Points = Points Scoped - Accepted Points - Rejected Points
		spillover_raw = total_scoped_raw - total_accepted_raw - total_rejected_raw

		# Round display values after rate calculation
		total_scoped = flt(total_scoped_raw, 1)
		total_accepted = flt(total_accepted_raw, 1)
		total_rejected = flt(total_rejected_raw, 1)
		spillover = flt(spillover_raw, 1)

		# Date range across all sprints for this developer
		sprint_docs = [sprint_map[s] for s in sprint_names_for_dev if s in sprint_map]
		earliest_start = min((s.start_date for s in sprint_docs if s.start_date), default=None)
		latest_end = max((s.end_date for s in sprint_docs if s.end_date), default=None)

		# Comma-separated sprint names as clickable links (sorted by start date)
		sorted_sprints = sorted(sprint_docs, key=lambda s: s.start_date or "")
		sprint_links = []
		for s in sorted_sprints:
			url = frappe.utils.get_url_to_form("Sprint", s.name)
			sprint_links.append(
				'<a href="{url}" data-doctype="Sprint" data-name="{name}">{name}</a>'.format(
					url=url, name=frappe.utils.escape_html(s.name)
				)
			)
		sprint_label = ", ".join(sprint_links)

		data.append({
			"developer": user_full_name_map.get(user, user),
			"sprints": sprint_label,
			"sprint_start_date": earliest_start,
			"sprint_end_date": latest_end,
			"no_of_sprints": no_of_sprints,
			"working_days": working_days,
			"public_holidays": public_holidays,
			"leave_days": flt(leave_days, 2),
			"target_points": target_points,
			"points_scoped": total_scoped,
			"percentage_target": flt((total_scoped_raw / prorated_target * 100) if prorated_target else 0.0, 2),
			"accepted_points": total_accepted,
			"rejected_points": total_rejected,
			"spillover_points": spillover,
			"acceptance_rate": flt(acceptance_rate, 2),
		})

	# Sort by developer name
	data.sort(key=lambda x: x.get("developer") or "")
	return data
