// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

frappe.query_reports["Sprint Report per Developer"] = {
	"filters": [
		{
			"fieldname": "start_date",
			"label": __("Start Date"),
			"fieldtype": "Date",
			"default": (function () {
				let d = new Date();
				d.setDate(1);
				while (d.getDay() !== 3) {
					d.setDate(d.getDate() + 1);
				}
				return frappe.datetime.obj_to_str(d);
			})(),
			"reqd": 1
		},
		{
			"fieldname": "end_date",
			"label": __("End Date"),
			"fieldtype": "Date",
			"default": (function () {
				let d = new Date();
				d.setMonth(d.getMonth() + 1);
				d.setDate(0);
				while (d.getDay() !== 2) {
					d.setDate(d.getDate() - 1);
				}
				return frappe.datetime.obj_to_str(d);
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
