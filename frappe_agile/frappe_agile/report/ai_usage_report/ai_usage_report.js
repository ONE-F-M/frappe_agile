// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

frappe.query_reports["AI Usage Report"] = {
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
		}
	]
};
