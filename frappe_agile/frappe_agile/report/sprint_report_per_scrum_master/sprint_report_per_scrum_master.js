// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

const REPORT_METHOD = "frappe_agile.frappe_agile.report.sprint_report_per_scrum_master.sprint_report_per_scrum_master";

// A project is only on the report once it is on the Roadmap, which is the
// Roadmap board's own membership rule.
const ROADMAP_PROJECT_FILTERS = {
	project_type: "SCRUM Project",
	is_active: "Yes",
	custom_show_in_roadmap: "Yes",
};

frappe.query_reports["Sprint Report per Scrum Master"] = {
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
			"fieldname": "project",
			"label": __("Project"),
			"fieldtype": "MultiSelectList",
			"get_data": function (txt) {
				// Only roadmap SCRUM projects — the same set the report rows come from.
				return get_link_options_selected_first("Project", "project", txt, ROADMAP_PROJECT_FILTERS);
			}
		},
		{
			"fieldname": "sprint",
			"label": __("Sprint"),
			"fieldtype": "MultiSelectList",
			"get_data": function (txt) {
				return get_link_options_selected_first("Sprint", "sprint", txt);
			}
		},
		{
			"fieldname": "scrum_master",
			"label": __("Scrum Master"),
			"fieldtype": "MultiSelectList",
			"get_data": function (txt) {
				// Only the Employees who are Project Manager on a roadmap SCRUM project.
				return get_options_selected_first("scrum_master", txt, `${REPORT_METHOD}.scrum_master_options`);
			}
		}
	],
	"formatter": function (value, row, column, data, default_formatter) {
		if (column.fieldname === "sprints" && value) {
			return value;
		}
		return default_formatter(value, row, column, data);
	}
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

function get_link_options_selected_first(doctype, fieldname, txt, filters = {}) {
	return frappe.db
		.get_link_options(doctype, txt, filters)
		.then((options) => selected_first(fieldname, options));
}

function get_options_selected_first(fieldname, txt, method) {
	return frappe.xcall(method, { txt: txt }).then((options) => selected_first(fieldname, options));
}
