# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt

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
		columns.insert(0, {"fieldname": "business_analyst", "label": "Business Analyst", "fieldtype": "Data", "width": 150})
		points_label = "Total Points Scoped"
	else:
		columns.insert(0, {"fieldname": "developer", "label": "Developer", "fieldtype": "Data", "width": 150})
		points_label = "Total Points Assigned"

	columns.append({"fieldname": "target_points", "label": "Target Points", "fieldtype": "Float", "width": 130})
	columns.append({"fieldname": "total_points", "label": points_label, "fieldtype": "Float", "width": 150})
	columns.append({"fieldname": "pct_completed", "label": "% Completed", "fieldtype": "Percent", "width": 130})
	columns.append({"fieldname": "pct_acceptance", "label": "% Acceptance", "fieldtype": "Percent", "width": 130})
	
	return columns

def get_data(filters):
	if not filters:
		filters = {}
		
	party = filters.get("party", "Business Analyst")
	Sprint = frappe.qb.DocType("Sprint")
	query = (
		frappe.qb.from_(Sprint)
		.select(Sprint.name, Sprint.start_date, Sprint.end_date, Sprint.business_analyst)
		.orderby(Sprint.start_date, order=frappe.qb.desc)
	)
	
	if filters.get("start_date") and filters.get("end_date"):
		# Sprints that overlap within the selected dates
		query = query.where(Sprint.start_date <= filters.get("end_date"))
		query = query.where(Sprint.end_date >= filters.get("start_date"))
		
	if filters.get("sprint"):
		query = query.where(Sprint.name == filters.get("sprint"))
		
	if party == "Business Analyst":
		if filters.get("business_analyst"):
			query = query.where(Sprint.business_analyst == filters.get("business_analyst"))
		else:
			# Exclude sprints with no BA as requested
			query = query.where(Sprint.business_analyst.isnotnull())
			query = query.where(Sprint.business_analyst != "")
		
	sprints = query.run(as_dict=True)
	if not sprints:
		return []

	sprint_names = [s.name for s in sprints]
	sprint_map = {s.name: s for s in sprints}
	
	SprintItem = frappe.qb.DocType("Sprint Work Item")
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
	
	# Target Velocity from Settings
	if party == "Business Analyst":
		target_velocity = flt(frappe.db.get_single_value("Frappe Agile Settings", "ba_velocity"))
	else:
		target_velocity = flt(frappe.db.get_single_value("Frappe Agile Settings", "developer_velocity"))

	# Group by (sprint, user)
	grouped_data = {}
	
	for wi in work_items:
		sprint_name = wi.sprint
		
		if party == "Business Analyst":
			user = sprint_map[sprint_name].business_analyst
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
				"total_points": 0.0,
				"points_completed": 0.0,
				"points_accepted": 0.0
			}
			
		points = flt(wi.story_points)
		grouped_data[key]["total_points"] += points
		
		if wi.status in ["Done", "In Staging"]:
			grouped_data[key]["points_completed"] += points
			
		if wi.status == "Done":
			grouped_data[key]["points_accepted"] += points
			
	data = []
	
	# Fetch all user full names for mapping
	involved_users = set()
	for (sprint_name, user) in grouped_data.keys():
		involved_users.add(user)
		
	user_full_name_map = {}
	if involved_users:
		users_data = frappe.get_all("User", 
			filters={"name": ["in", list(involved_users)]}, 
			fields=["name", "full_name"]
		)
		user_full_name_map = {u.name: u.full_name or u.name for u in users_data}

	for (sprint_name, user), metrics in grouped_data.items():
		sprint_doc = sprint_map.get(sprint_name)
		
		total_points = metrics["total_points"]
		points_completed = metrics["points_completed"]
		points_accepted = metrics["points_accepted"]
		
		# Percentages use total_points as denominator
		pct_completed = (points_completed / total_points) * 100 if total_points else 0.0
		pct_acceptance = (points_accepted / total_points) * 100 if total_points else 0.0

		full_name = user_full_name_map.get(user, user)

		row = {
			"sprint": sprint_name,
			"sprint_start_date": sprint_doc.start_date,
			"sprint_end_date": sprint_doc.end_date,
			"target_points": target_velocity,
			"total_points": total_points,
			"pct_completed": pct_completed,
			"pct_acceptance": pct_acceptance
		}
		
		if party == "Business Analyst":
			row["business_analyst"] = full_name
		else:
			row["developer"] = full_name
			
		data.append(row)
		
	# Sort data by start date desc
	data.sort(key=lambda x: (x.get("sprint_start_date") or "", x.get("sprint") or ""), reverse=True)
		
	return data
