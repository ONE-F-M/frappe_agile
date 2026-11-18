// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt


frappe.query_reports["Sprint Report per Developer"] = {
	"filters": [
		{
			"fieldname": "start_date",
			"label": __("Start Date"),
			"fieldtype": "Date",
			"default": (function () {
				// Wednesday that started the last completed sprint (sprints run Wednesday to Tuesday)
				let today = new Date();
				let day = today.getDay();
				let daysSinceTue = (day + 7 - 2) % 7 || 7;
				let lastTuesday = new Date(today);
				lastTuesday.setDate(today.getDate() - daysSinceTue);
				let startWed = new Date(lastTuesday);
				startWed.setDate(lastTuesday.getDate() - 6);
				return frappe.datetime.obj_to_str(startWed);
			})(),
			"reqd": 1,
			"on_change": function () {
				// Move End Date to the Tuesday that closes the sprint starting on the chosen date
				let start = frappe.query_report.get_filter_value("start_date");
				if (start) {
					let d = new Date(start);
					let day = d.getDay();
					let daysToTue = (2 - day + 7) % 7;
					if (daysToTue === 0) daysToTue = 7;
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
				// Tuesday that ended the last completed sprint
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
			"fieldtype": "MultiSelectList",
			"get_data": function (txt) {
				return get_options_selected_first("Sprint", "sprint", txt);
			}
		},
		{
			"fieldname": "developer",
			"label": __("Developer"),
			"fieldtype": "MultiSelectList",
			"get_data": function (txt) {
				// The Development Team, by name — nobody else can produce a row.
				// The report defaults to all of them, so the filter starts empty.
				return get_team_options_selected_first("developer", txt);
			}
		}
	]
};


// Put selected values first, then the search results.
function selected_first(fieldname, options) {
	const selected = frappe.query_report.get_filter_value(fieldname) || [];
	const by_value = Object.fromEntries(options.map((o) => [o.value, o]));
	const selected_options = selected.map(
		(v) => by_value[v] || { value: v, label: v, description: "" }
	);
	const rest = options.filter((o) => !selected.includes(o.value));
	return selected_options.concat(rest);
}

function get_options_selected_first(doctype, fieldname, txt) {
	return frappe.db
		.get_link_options(doctype, txt)
		.then((options) => selected_first(fieldname, options));
}

function get_team_options_selected_first(fieldname, txt) {
	return frappe
		.xcall(
			"frappe_agile.frappe_agile.report.sprint_report_per_developer.sprint_report_per_developer.developer_options",
			{ txt: txt }
		)
		.then((options) => selected_first(fieldname, options));
}
