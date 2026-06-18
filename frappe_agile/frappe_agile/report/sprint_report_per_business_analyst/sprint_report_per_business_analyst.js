// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

frappe.query_reports["Sprint Report per Business Analyst"] = {
	"filters": [
		{
			"fieldname": "start_date",
			"label": __("Start Date"),
			"fieldtype": "Date",
			"default": (function () {
				// Last completed sprint: preceding Wednesday
				// A sprint runs Wednesday → Tuesday.
				// Find the most recent Tuesday (last sprint end), then go back 6 days to its Wednesday.
				let today = new Date();
				let day = today.getDay(); // 0=Sun … 6=Sat
				// Days since last Tuesday (day 2)
				let daysSinceTue = (day + 7 - 2) % 7 || 7; // at least 1 day back
				let lastTuesday = new Date(today);
				lastTuesday.setDate(today.getDate() - daysSinceTue);
				// The Wednesday that started that sprint is 6 days before that Tuesday
				let startWed = new Date(lastTuesday);
				startWed.setDate(lastTuesday.getDate() - 6);
				return frappe.datetime.obj_to_str(startWed);
			})(),
			"reqd": 1,
			"on_change": function () {
				// Auto-update end_date to the Tuesday following the selected start_date
				let start = frappe.query_report.get_filter_value("start_date");
				if (start) {
					let d = new Date(start);
					let day = d.getDay();
					// If it's a Wednesday (3), add 6 days to reach Tuesday
					// Otherwise find the next Tuesday from the given date
					let daysToTue = (2 - day + 7) % 7;
					if (daysToTue === 0) daysToTue = 7; // if already Tuesday, go to next
					// For a Wednesday start, we want the same-week Tuesday (6 days later)
					if (day === 3) {
						daysToTue = 6;
					}
					d.setDate(d.getDate() + daysToTue);
					frappe.query_report.set_filter_value("end_date", frappe.datetime.obj_to_str(d));
				}
			}
		},
		{
			"fieldname": "end_date",
			"label": __("End Date"),
			"fieldtype": "Date",
			"default": (function () {
				// Last completed sprint: preceding Tuesday
				let today = new Date();
				let day = today.getDay();
				let daysSinceTue = (day + 7 - 2) % 7 || 7;
				let lastTuesday = new Date(today);
				lastTuesday.setDate(today.getDate() - daysSinceTue);
				return frappe.datetime.obj_to_str(lastTuesday);
			})(),
			"reqd": 1
		},
		{
			"fieldname": "sprint",
			"label": __("Sprint"),
			"fieldtype": "Link",
			"options": "Sprint"
		},
		{
			"fieldname": "business_analyst",
			"label": __("Business Analyst"),
			"fieldtype": "Link",
			"options": "User"
		}
	],
	"formatter": function (value, row, column, data, default_formatter) {
		if (column.fieldname === "sprints" && value) {
			return value;
		}
		return default_formatter(value, row, column, data);
	}
};
