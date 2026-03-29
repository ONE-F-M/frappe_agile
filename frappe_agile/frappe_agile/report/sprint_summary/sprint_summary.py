# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data

def get_columns():
	return [
		{
			"fieldname": "sprint",
			"label": _("Sprint"),
			"fieldtype": "Link",
			"options": "Sprint",
			"width": 150
		},
		{
			"fieldname": "percentage_of_target_achieved",
			"label": _("Percentage of Target Achieved"),
			"fieldtype": "Percent",
			"width": 210
		},
		{
			"fieldname": "accepted_points",
			"label": _("Accepted Points"),
			"fieldtype": "Float",
			"width": 150
		},
		{
			"fieldname": "percentage_of_accepted_points",
			"label": _("Percentage of Accepted Points"),
			"fieldtype": "Percent",
			"width": 220
		},
		{
			"fieldname": "not_completed_points",
			"label": _("Not Completed Points"),
			"fieldtype": "Float",
			"width": 180
		},
		{
			"fieldname": "total_number_of_story",
			"label": _("Total Number of Story"),
			"fieldtype": "Int",
			"width": 180
		},
		{
			"fieldname": "total_number_of_task",
			"label": _("Total Number of Task"),
			"fieldtype": "Int",
			"width": 180
		},
		{
			"fieldname": "total_number_of_bugs",
			"label": _("Total Number of Bugs"),
			"fieldtype": "Int",
			"width": 180
		}
	]

def get_data(filters):
	# Only show completed sprints (acceptance criteria: "when Sprint is marked as complete")
	sprint_filters = {"status": "Completed"}
	if filters and filters.get("sprint"):
		sprint_filters["name"] = filters.get("sprint")
		
	# Get all matching Sprints
	sprints = frappe.get_all("Sprint", filters=sprint_filters, fields=["name", "target_points"])
	
	if not sprints:
		return []
		
	sprint_names = [s.name for s in sprints]
	
	# Get all Work Items for these sprints
	work_items = frappe.get_all("Work Item", 
		filters={"sprint": ["in", sprint_names]},
		fields=["sprint", "work_item_type", "status", "story_points"]
	)
	
	# Group work items by sprint
	wi_by_sprint = {}
	for wi in work_items:
		wi_by_sprint.setdefault(wi.sprint, []).append(wi)
		
	data = []
	
	for sprint in sprints:
		target_points = flt(sprint.target_points)
		items = wi_by_sprint.get(sprint.name, [])

		if not items and target_points == 0:
			continue  # Skip sprints with no work items and no target points
			
		accepted_points = 0.0
		total_points = 0.0
		story_count = 0
		task_count = 0
		bug_count = 0
		
		for wi in items:
			pts = flt(wi.story_points)
			total_points += pts
			
			# Assuming 'Done' is the accepted status
			if wi.status == "Done":
				accepted_points += pts
				
			if wi.work_item_type == "User Story":
				story_count += 1
			elif wi.work_item_type == "Task":
				task_count += 1
			elif wi.work_item_type == "Bug":
				bug_count += 1
				
		# Calculations
		pct_target_achieved = (accepted_points / target_points * 100.0) if target_points > 0 else 0.0
		pct_accepted_points = (accepted_points / total_points * 100.0) if total_points > 0 else 0.0
		not_completed_points = total_points - accepted_points
		
		data.append({
			"sprint": sprint.name,
			"percentage_of_target_achieved": pct_target_achieved,
			"accepted_points": accepted_points,
			"percentage_of_accepted_points": pct_accepted_points,
			"not_completed_points": not_completed_points,
			"total_number_of_story": story_count,
			"total_number_of_task": task_count,
			"total_number_of_bugs": bug_count
		})
		
	# Sort data by sprint name
	data.sort(key=lambda x: x["sprint"])
	return data
