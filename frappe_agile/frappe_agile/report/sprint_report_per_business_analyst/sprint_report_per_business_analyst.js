// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

frappe.query_reports["Sprint Report per Business Analyst"] = {
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
