# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import formatdate, flt

def execute(filters=None):
	if not filters:
		filters = {}
	columns = get_columns(filters)
	data = get_data(filters)
	return columns, data

def get_columns(filters):
	party = filters.get("party", "Business Analyst")
	columns = [
		{"fieldname": "sprint", "label": "Sprint", "fieldtype": "Link", "options": "Sprint", "width": 150},
		{"fieldname": "sprint_start_date", "label": "Sprint Start Date", "fieldtype": "Date", "width": 150},
		{"fieldname": "sprint_end_date", "label": "Sprint End Date", "fieldtype": "Date", "width": 150},
	]

	if party == "Business Analyst":
		columns.append({"fieldname": "business_analyst", "label": "Business Analyst", "fieldtype": "Link", "options": "User", "width": 150})
	else:
		columns.append({"fieldname": "developer", "label": "Developer", "fieldtype": "Link", "options": "User", "width": 150})
	columns.append({"fieldname": "total_planned_points", "label": "Total Planned Points", "fieldtype": "Float", "width": 150})
	columns.append({"fieldname": "total_estimated_points", "label": "Total Estimated Points", "fieldtype": "Float", "width": 160})
	columns.append({"fieldname": "target_actual_points", "label": "Target Actual Points", "fieldtype": "Float", "width": 160})
	columns.append({"fieldname": "accepted_points", "label": "Accepted Points", "fieldtype": "Float", "width": 160})
	columns.append({"fieldname": "target_performance", "label": "Target Performance %", "fieldtype": "Percent", "width": 160})
	columns.append({"fieldname": "completion_rate", "label": "Completion Rate %", "fieldtype": "Percent", "width": 160})
	columns.append({"fieldname": "acceptance_rate", "label": "Acceptance Rate %", "fieldtype": "Percent", "width": 160})
	
	return columns

def get_data(filters):
	if not filters:
		filters = {}
		
	Sprint = frappe.qb.DocType("Sprint")
	query = (
		frappe.qb.from_(Sprint)
		.select(Sprint.name, Sprint.start_date, Sprint.end_date)
		.orderby(Sprint.start_date, order=frappe.qb.desc)
	)
	
	if filters.get("start_date") and filters.get("end_date"):
		# Sprints that overlap within the selected dates
		query = query.where(Sprint.start_date <= filters.get("end_date"))
		query = query.where(Sprint.end_date >= filters.get("start_date"))
		
	if filters.get("sprint"):
		query = query.where(Sprint.name == filters.get("sprint"))
		
	sprints = query.run(as_dict=True)
	if not sprints:
		return []

	sprint_names = [s.name for s in sprints]
	sprint_map = {s.name: s for s in sprints}
	
	party = filters.get("party", "Business Analyst")
	
	SprintItem = frappe.qb.DocType("Sprint Work Item")
	
	if party == "Business Analyst":
		WorkItem = frappe.qb.DocType("Work Item")
		wi_query = (
			frappe.qb.from_(SprintItem)
			.join(WorkItem).on(SprintItem.work_item == WorkItem.name)
			.select(
				SprintItem.parent.as_("sprint"),
				WorkItem.owner,
				SprintItem.story_points,
				SprintItem.status
			)
			.where(SprintItem.parent.isin(sprint_names))
			.where(SprintItem.work_item_type.isin(["User Story", "Task"]))
		)
	else:
		wi_query = (
			frappe.qb.from_(SprintItem)
			.select(
				SprintItem.parent.as_("sprint"),
				SprintItem.assignee_user,
				SprintItem.story_points,
				SprintItem.status
			)
			.where(SprintItem.parent.isin(sprint_names))
			.where(SprintItem.work_item_type.isin(["User Story", "Task"]))
		)
	
	work_items = wi_query.run(as_dict=True)
	
	# Group by (sprint, user)
	grouped_data = {}
	
	for wi in work_items:
		sprint_name = wi.sprint
		
		if party == "Business Analyst":
			user = wi.owner
			# Apply filter if set
			if filters.get("business_analyst") and user != filters.get("business_analyst"):
				continue
		else:
			user = wi.assignee_user
			# Apply filter if set
			if filters.get("developer") and user != filters.get("developer"):
				continue
				
		if not user:
			continue
			
		key = (sprint_name, user)
		if key not in grouped_data:
			grouped_data[key] = {
				"total_estimated_points": 0.0,
				"target_actual_points": 0.0,
				"accepted_points": 0.0
			}
			
		grouped_data[key]["total_estimated_points"] += flt(wi.story_points)
		
		if wi.status in ["Done", "In Staging"]:
			grouped_data[key]["target_actual_points"] += flt(wi.story_points)
			
		if wi.status == "Done":
			grouped_data[key]["accepted_points"] += flt(wi.story_points)
			
	data = []
	for (sprint_name, user), metrics in grouped_data.items():
		sprint_doc = sprint_map.get(sprint_name)
		
		total_planned_points = 80.0
		total_estimated_points = metrics["total_estimated_points"]
		target_actual_points = metrics["target_actual_points"]
		accepted_points = metrics["accepted_points"]
		
		target_performance = (total_estimated_points / total_planned_points) * 100 if total_planned_points else 0.0
		completion_rate = (target_actual_points / total_planned_points) * 100 if total_planned_points else 0.0
		acceptance_rate = (accepted_points / total_planned_points) * 100 if total_planned_points else 0.0

		row = {
			"sprint": sprint_name,
			"sprint_start_date": sprint_doc.start_date,
			"sprint_end_date": sprint_doc.end_date,
			"total_planned_points": total_planned_points,
			"total_estimated_points": total_estimated_points,
			"target_actual_points": target_actual_points,
			"accepted_points": accepted_points,
			"target_performance": target_performance,
			"completion_rate": completion_rate,
			"acceptance_rate": acceptance_rate
		}
		
		if party == "Business Analyst":
			row["business_analyst"] = user
		else:
			row["developer"] = user
			
		data.append(row)
		
	# Sort data
	data.sort(key=lambda x: x.get("sprint") or "", reverse=True)
		
	return data
