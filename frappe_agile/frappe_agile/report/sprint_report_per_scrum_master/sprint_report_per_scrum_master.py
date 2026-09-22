# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

"""Sprint performance per Scrum Master.

A Scrum Master here is an Employee set as Project Manager on a roadmap SCRUM
project, so the row axis comes from the Project rather than from the Sprint. The
sprints on a row are the sprints of the projects that person manages which
overlap the reported window by at least one day, and the money columns are those
sprints added up.

Rows are the people with at least one such sprint: a row with no sprint has no
date range, and the proration is measured over the row's own sprints. New Work
Items is the one column measured over the filter's dates instead — it counts
what the person created in the reported window, whichever sprint it went to.
"""

import frappe
from frappe.utils import flt, getdate

from frappe_agile.frappe_agile.page.roadmap_board.roadmap_board import (
	ROADMAP_FLAG_FIELD,
	ROADMAP_FLAG_ON,
	SCRUM_PROJECT_TYPE,
)
from frappe_agile.frappe_agile.report.proration import (
	as_list,
	get_proration,
	get_target,
)

# The work item types that carry story points.
SCOPED_WORK_ITEM_TYPES = ("User Story", "Task", "Bug")


def execute(filters=None):
	if not filters:
		filters = {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"fieldname": "scrum_master", "label": "Scrum Master", "fieldtype": "Data", "width": 180},
		{"fieldname": "sprints", "label": "Sprint(s)", "fieldtype": "HTML", "width": 200},
		{"fieldname": "sprint_start_date", "label": "Start Date", "fieldtype": "Date", "width": 150},
		{"fieldname": "sprint_end_date", "label": "End Date", "fieldtype": "Date", "width": 150},
		{"fieldname": "no_of_sprints", "label": "No. of Sprints", "fieldtype": "Int", "width": 120},
		{"fieldname": "new_work_items", "label": "New Work Items", "fieldtype": "Int", "width": 140},
		{"fieldname": "days", "label": "Working / Holiday / Leave Days", "fieldtype": "Data", "width": 200},
		{"fieldname": "expected_velocity", "label": "Expected Velocity", "fieldtype": "Float", "width": 150},
		{"fieldname": "points_scoped", "label": "Points Scoped", "fieldtype": "Float", "width": 130},
		{"fieldname": "percentage_target", "label": "Percentage Target %", "fieldtype": "Percent", "width": 160},
		{"fieldname": "accepted_points", "label": "Accepted Points", "fieldtype": "Float", "width": 140},
		{"fieldname": "rejected_points", "label": "Rejected Points", "fieldtype": "Float", "width": 140},
		{"fieldname": "spillover_points", "label": "Spillover Points", "fieldtype": "Float", "width": 140},
		{"fieldname": "acceptance_rate", "label": "Acceptance Rate %", "fieldtype": "Percent", "width": 150},
	]


def get_scrum_master_projects(selected_projects=None, selected_masters=None):
	"""Roadmap SCRUM projects that have a Project Manager, keyed by project.

	Membership is the Roadmap board's rule and the user cannot widen it: Project
	Type "SCRUM Project", Is Active "Yes", Show in Roadmap "Yes".
	"""
	filters = {
		"project_type": SCRUM_PROJECT_TYPE,
		"is_active": "Yes",
		ROADMAP_FLAG_FIELD: ROADMAP_FLAG_ON,
		"project_manager": ["is", "set"],
	}
	if selected_projects:
		filters["name"] = ["in", selected_projects]
	if selected_masters:
		filters["project_manager"] = ["in", selected_masters]

	projects = frappe.get_all("Project", filters=filters, fields=["name", "project_manager"])
	return {p.name: p.project_manager for p in projects}


@frappe.whitelist()
def scrum_master_options(txt=None):
	"""The Employees who are Project Manager on a roadmap SCRUM project.

	The filter offers only these, because nobody else can produce a row.
	"""
	frappe.has_permission("Project", "read", throw=True)

	employees = set(get_scrum_master_projects().values())
	if not employees:
		return []

	filters = {"name": ["in", sorted(employees)]}
	if txt:
		filters["employee_name"] = ["like", f"%{txt}%"]

	return [
		{"value": e.name, "description": e.employee_name or e.name}
		for e in frappe.get_all(
			"Employee", filters=filters, fields=["name", "employee_name"], order_by="employee_name asc"
		)
	]


def get_data(filters):
	if not filters:
		filters = {}

	# ------------------------------------------------------------------
	# 1. The Scrum Masters and the projects they manage
	# ------------------------------------------------------------------
	project_master = get_scrum_master_projects(
		selected_projects=as_list(filters.get("project")),
		selected_masters=as_list(filters.get("scrum_master")),
	)
	if not project_master:
		return []

	# ------------------------------------------------------------------
	# 2. Sprints of those projects overlapping the window by at least a day
	# ------------------------------------------------------------------
	sprints = get_sprints(list(project_master), filters)
	if not sprints:
		return []

	# scrum master -> { sprint name -> sprint }, so a sprint is counted once
	master_sprints = {}
	for sprint in sprints:
		master_sprints.setdefault(project_master[sprint.project], {})[sprint.name] = sprint

	# ------------------------------------------------------------------
	# 3. Story points per sprint
	# ------------------------------------------------------------------
	points = get_sprint_points([s.name for s in sprints])

	# ------------------------------------------------------------------
	# 4. The people themselves, and the velocity their target comes from
	# ------------------------------------------------------------------
	employees = frappe.get_all(
		"Employee",
		filters={"name": ["in", list(master_sprints)]},
		fields=["name", "employee_name", "user_id"],
	)
	employee_map = {e.name: e for e in employees}
	velocity = flt(frappe.db.get_single_value("Frappe Agile Settings", "ba_velocity"))

	# ------------------------------------------------------------------
	# 5. One row per Scrum Master, aggregated across their sprints
	# ------------------------------------------------------------------
	data = []

	for master, sprint_map in master_sprints.items():
		sprint_docs = sorted(sprint_map.values(), key=lambda s: s.start_date or "")
		periods = [(s.start_date, s.end_date) for s in sprint_docs]

		# Expected Velocity = the velocity over the days this person could
		# actually work, counting each date once however many sprints cover it.
		working_days, public_holidays, leave_days = get_proration(master, periods)
		prorated_target = get_target(velocity, working_days)

		scoped = sum(points[s.name]["scoped"] for s in sprint_docs)
		accepted = sum(points[s.name]["accepted"] for s in sprint_docs)
		rejected = sum(points[s.name]["rejected"] for s in sprint_docs)

		# Spillover = what was scoped and neither accepted nor rejected.
		spillover = scoped - accepted - rejected

		earliest_start = min((s.start_date for s in sprint_docs if s.start_date), default=None)
		latest_end = max((s.end_date for s in sprint_docs if s.end_date), default=None)

		employee = employee_map.get(master)
		data.append({
			"scrum_master": (employee.employee_name if employee else None) or master,
			"sprints": get_sprint_links(sprint_docs),
			"sprint_start_date": earliest_start,
			"sprint_end_date": latest_end,
			"no_of_sprints": len(sprint_docs),
			# Counted over the reported window, not the row's sprints: it answers
			# "how much did this person raise in the period", whatever it was
			# filed under. Falls back to the row's own range on a call with no dates.
			"new_work_items": count_new_work_items(
				employee.user_id if employee else None,
				filters.get("start_date") or earliest_start,
				filters.get("end_date") or latest_end,
			),
			"days": "{0} / {1} / {2}".format(working_days, public_holidays, flt(leave_days, 2)),
			"expected_velocity": flt(prorated_target, 1),
			"points_scoped": flt(scoped, 1),
			"percentage_target": flt((scoped / prorated_target * 100) if prorated_target else 0.0, 2),
			"accepted_points": flt(accepted, 1),
			"rejected_points": flt(rejected, 1),
			"spillover_points": flt(spillover, 1),
			"acceptance_rate": flt((accepted / prorated_target * 100) if prorated_target else 0.0, 2),
		})

	data.sort(key=lambda row: row.get("scrum_master") or "")
	return data


def get_sprints(project_names, filters):
	"""Sprints of these projects that overlap the reported window by a day or more."""
	Sprint = frappe.qb.DocType("Sprint")
	query = (
		frappe.qb.from_(Sprint)
		.select(Sprint.name, Sprint.start_date, Sprint.end_date, Sprint.project)
		.where(Sprint.project.isin(project_names))
		.orderby(Sprint.start_date, order=frappe.qb.desc)
	)

	if filters.get("start_date") and filters.get("end_date"):
		query = query.where(Sprint.start_date <= filters.get("end_date"))
		query = query.where(Sprint.end_date >= filters.get("start_date"))

	selected_sprints = as_list(filters.get("sprint"))
	if selected_sprints:
		query = query.where(Sprint.name.isin(selected_sprints))

	return query.run(as_dict=True)


def get_sprint_points(sprint_names):
	"""Scoped, accepted and rejected points per sprint."""
	points = {name: {"scoped": 0.0, "accepted": 0.0, "rejected": 0.0} for name in sprint_names}
	if not sprint_names:
		return points

	SprintItem = frappe.qb.DocType("Sprint Work Item")
	rows = (
		frappe.qb.from_(SprintItem)
		.select(
			SprintItem.parent.as_("sprint"),
			SprintItem.story_points,
			SprintItem.status,
		)
		.where(SprintItem.parent.isin(sprint_names))
		.where(SprintItem.work_item_type.isin(list(SCOPED_WORK_ITEM_TYPES)))
	).run(as_dict=True)

	for row in rows:
		sprint = points.get(row.sprint)
		if sprint is None:
			continue
		story_points = flt(row.story_points)
		# Everything in the sprint was scoped; where it ended up decides the rest.
		sprint["scoped"] += story_points
		if row.status == "Done":
			sprint["accepted"] += story_points
		elif row.status == "Rejected":
			sprint["rejected"] += story_points

	return points


def count_new_work_items(user, start_date, end_date):
	"""Work items this person created between the two dates, in any sprint or none.

	Deliberately not tied to the row's sprints: an Epic in no sprint, or an item
	filed under a project the filter left out, is still work this person raised in
	the period, and that is what the column reports.
	"""
	if not (user and start_date and end_date):
		return 0

	# creation is a datetime, so the bounds are spelled out: a bare end date
	# would drop everything created on the last day after midnight.
	return frappe.db.count(
		"Work Item",
		{
			"owner": user,
			"creation": [
				"between",
				[f"{getdate(start_date)} 00:00:00", f"{getdate(end_date)} 23:59:59.999999"],
			],
		},
	)


def get_sprint_links(sprint_docs):
	"""The sprint names as clickable links, oldest first."""
	links = []
	for sprint in sprint_docs:
		links.append(
			'<a href="{url}" data-doctype="Sprint" data-name="{name}">{name}</a>'.format(
				url=frappe.utils.get_url_to_form("Sprint", sprint.name),
				name=frappe.utils.escape_html(sprint.name),
			)
		)
	return ", ".join(links)
