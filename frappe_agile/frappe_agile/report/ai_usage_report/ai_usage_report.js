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
	],
	"formatter": function (value, row, column, data, default_formatter) {
		if (column.fieldname === "ai_tools_feedback" && value) {
			let escaped = frappe.utils.escape_html(value);
			return `<div class="ai-feedback-cell">${escaped}</div>`;
		}
		return default_formatter(value, row, column, data);
	},
	"get_datatable_options": function (options) {
		Object.assign(options, {
			cellHeight: 300
		});
		return options;
	},
	"onload": function (report) {
		if (!document.getElementById("ai-usage-report-style")) {
			let style = document.createElement("style");
			style.id = "ai-usage-report-style";
			style.textContent = `
				.ai-feedback-cell {
					white-space: pre-line;
					line-height: 1.5;
					max-height: 280px;
					overflow-y: auto;
					padding-right: 4px;
				}
				.dt-cell--col-5 .dt-cell__content {
					overflow: visible !important;
				}
			`;
			document.head.appendChild(style);
		}
	}
};
