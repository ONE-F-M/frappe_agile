# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt

from frappe_agile.frappe_agile.doctype.frappe_agile_settings.frappe_agile_settings import (
	development_team_users,
)
from frappe_agile.frappe_agile.report.proration import (
	as_list,
	get_employee_map,
	get_proration,
	get_target,
)


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
		{"fieldname": "days", "label": "Working / Holiday / Leave Days", "fieldtype": "Data", "width": 200},
		{"fieldname": "target_points", "label": "Target Points", "fieldtype": "Float", "width": 130},
		{"fieldname": "points_scoped", "label": "Points Scoped", "fieldtype": "Float", "width": 130},
		{"fieldname": "percentage_target", "label": "Scoped Percentage", "fieldtype": "Percent", "width": 160},
		{"fieldname": "accepted_points", "label": "Accepted Points", "fieldtype": "Float", "width": 140},
		{"fieldname": "accepted_per_target", "label": "Target Achievement Percentage", "fieldtype": "Percent", "width": 200},
		{"fieldname": "rejected_points", "label": "Rejected Points", "fieldtype": "Float", "width": 140},
		{"fieldname": "spillover_points", "label": "Spillover Points", "fieldtype": "Float", "width": 140},
		{"fieldname": "acceptance_rate", "label": "Acceptance Rate Percentage", "fieldtype": "Percent", "width": 150},
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

	selected_sprints = as_list(filters.get("sprint"))
	if selected_sprints:
		query = query.where(Sprint.name.isin(selected_sprints))

	sprints = query.run(as_dict=True)
	if not sprints:
		return []

	sprint_names = [s.name for s in sprints]
	sprint_map = {s.name: s for s in sprints}

	# ------------------------------------------------------------------
	# 2. Fetch work items (User Story, Task, and Bug only) from those sprints
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
		.where(SprintItem.work_item_type.isin(["User Story", "Task", "Bug"]))
	)
	work_items = wi_query.run(as_dict=True)

	# ------------------------------------------------------------------
	# 3. Developer velocity from settings
	# ------------------------------------------------------------------
	developer_velocity = flt(frappe.db.get_single_value("Frappe Agile Settings", "developer_velocity"))

	# The Development Team decides who is a developer. Without it the rows were
	# whoever happened to be assigned a work item — Administrator, an agent's
	# login, a manager who picked one up — each given a velocity target.
	team = development_team_users()
	selected_developers = [user for user in as_list(filters.get("developer")) or team if user in team]
	if not selected_developers:
		return []

	# ------------------------------------------------------------------
	# 4. Aggregate per (developer, sprint)
	# ------------------------------------------------------------------
	# developer -> { sprint -> {scoped, accepted, rejected} }
	dev_sprint_data = {}

	for wi in work_items:
		user = wi.assignee_user
		if not user:
			continue

		if user not in selected_developers:
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

		# Every sprint listed in Sprint(s) is counted. Distinct date ranges were
		# counted before, so three sprints sharing a week read as one.
		periods = [
			(sprint_map[s].start_date, sprint_map[s].end_date)
			for s in sprint_names_for_dev
			if s in sprint_map
		]
		no_of_sprints = len(periods)

		# Target Points = the developer's velocity over the days they could
		# actually work, counting each date once however many sprints cover it.
		employee = employee_map.get(user)
		working_days, public_holidays, leave_days = get_proration(employee, periods)
		prorated_target = get_target(developer_velocity, working_days)

		target_points = flt(prorated_target, 1)

		# Sum scoped, accepted, and rejected across all sprints
		total_scoped_raw = sum(v["scoped_points"] for v in sprint_dict.values())
		total_accepted_raw = sum(v["accepted_points"] for v in sprint_dict.values())
		total_rejected_raw = sum(v["rejected_points"] for v in sprint_dict.values())

		# Acceptance Rate = (Accepted Points / Target Points) × 100
		acceptance_rate = (total_accepted_raw / prorated_target * 100) if prorated_target else 0.0

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
			"days": "{0} / {1} / {2}".format(working_days, public_holidays, flt(leave_days, 2)),
			"target_points": target_points,
			"points_scoped": total_scoped,
			"percentage_target": flt((total_scoped_raw / prorated_target * 100) if prorated_target else 0.0, 2),
			"accepted_points": total_accepted,
			"rejected_points": total_rejected,
			"spillover_points": spillover,
			"acceptance_rate": flt(acceptance_rate, 2),
			"accepted_per_target": flt((total_accepted_raw / prorated_target * 100) if prorated_target else 0.0, 2),
		})

	# Sort by developer name
	data.sort(key=lambda x: x.get("developer") or "")
	return data


@frappe.whitelist()
def developer_options(txt=None):
	"""The Development Team, for the Developer filter.

	Only these can produce a row, and they are offered by name rather than by
	email address.
	"""
	frappe.has_permission("Sprint", "read", throw=True)

	team = development_team_users()
	if not team:
		return []

	filters = {"name": ["in", team]}
	if txt:
		filters["full_name"] = ["like", f"%{txt}%"]

	return [
		{"value": u.name, "description": u.full_name or u.name}
		for u in frappe.get_all(
			"User", filters=filters, fields=["name", "full_name"], order_by="full_name asc"
		)
	]
