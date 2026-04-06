# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt, formatdate

def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data

def get_columns():
	return [
		{"fieldname": "sprint", "label": "Sprint", "fieldtype": "Link", "options": "Sprint", "width": 150},
		{"fieldname": "sprint_start_date", "label": "SPRINT START DATE", "fieldtype": "Date", "width": 150},
		{"fieldname": "sprint_end_date", "label": "SPRINT END DATE", "fieldtype": "Date", "width": 150},
		{"fieldname": "spill_over", "label": "SPILL OVER", "fieldtype": "Float", "width": 120},
		{"fieldname": "scoped", "label": "SCOPED", "fieldtype": "Float", "width": 120},
		{"fieldname": "bug_points", "label": "Bug/HD Ticket", "fieldtype": "Float", "width": 120},
		{"fieldname": "total_points", "label": "TOTAL POINTS", "fieldtype": "Float", "width": 120},
		{"fieldname": "target_pts", "label": "TARGET PTS", "fieldtype": "Float", "width": 120},
		{"fieldname": "accepted", "label": "ACCEPTED", "fieldtype": "Float", "width": 120},
		{"fieldname": "age_accepted", "label": "%AGE ACCEPTED", "fieldtype": "Percent", "width": 120},
		{"fieldname": "not_completed", "label": "NOT COMPLETED", "fieldtype": "Float", "width": 140},
		{"fieldname": "features", "label": "FEATURES", "fieldtype": "Int", "width": 100},
		{"fieldname": "chores", "label": "CHORES", "fieldtype": "Int", "width": 100},
		{"fieldname": "backlogs", "label": "BACKLOGS", "fieldtype": "Int", "width": 100},
		{"fieldname": "bugs", "label": "BUGS", "fieldtype": "Int", "width": 100},
	]

def get_data(filters):
	data = []
	conditions = ""
	if filters and filters.get("sprint"):
		conditions = f"WHERE name = '{frappe.db.escape(filters.get('sprint'))}'"

	sprints = frappe.db.sql(f"""
		SELECT name, start_date, end_date, target_points
		FROM `tabSprint`
		{conditions}
		ORDER BY start_date DESC
	""", as_dict=True)

	# Global backlogs count
	# "BACKLOGS are work items with no sprint set" -> work items where sprint is NULL or empty
	backlogs_count = frappe.db.count("Work Item", {"sprint": ["in", ["", None]]})

	for sprint in sprints:
		# Fetch work items for this sprint
		work_items = frappe.get_all("Work Item", 
			filters={"sprint": sprint.name}, 
			fields=["name", "story_points", "work_item_type", "status"]
		)
		
		spill_over = 0.0 # pending future logic
		scoped = 0.0
		bug_points = 0.0
		accepted = 0.0
		features_count = 0
		chores_count = 0
		bugs_count = 0
		
		for wi in work_items:
			pts = flt(wi.story_points)
			if wi.work_item_type == "Bug":
				bug_points += pts
				bugs_count += 1
			else:
				# Scoped includes story points of all IN SPRINT non-bug items
				scoped += pts
				
				if wi.work_item_type == "User Story":
					features_count += 1
				elif wi.work_item_type == "Task":
					chores_count += 1

			# Accepted: status == "Done"
			if wi.status == "Done":
				accepted += pts

		total_points = spill_over + scoped + bug_points
		target_pts = flt(sprint.target_points)
		
		age_accepted = (accepted / total_points * 100) if total_points > 0 else 0.0
		not_completed = total_points - accepted

		start_dt = formatdate(sprint.start_date, "dd-MM-yyyy") if sprint.start_date else ""
		end_dt = formatdate(sprint.end_date, "dd-MM-yyyy") if sprint.end_date else ""

		data.append({
			"sprint": sprint.name,
			"sprint_start_date": start_dt,
			"sprint_end_date": end_dt,
			"spill_over": spill_over,
			"scoped": scoped,
			"bug_points": bug_points,
			"total_points": total_points,
			"target_pts": target_pts,
			"accepted": accepted,
			"age_accepted": age_accepted,
			"not_completed": not_completed,
			"features": features_count,
			"chores": chores_count,
			"backlogs": backlogs_count,
			"bugs": bugs_count
		})

	return data
