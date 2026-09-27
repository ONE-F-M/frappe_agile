// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

frappe.query_reports["Sprint Retro Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
			on_change: (report) => {
				const from_date = report.get_filter_value("from_date");
				const to_date = from_date && frappe.datetime.add_days(from_date, 6);
				// An unchanged to_date does not refresh the report, so refresh here.
				if (to_date && to_date !== report.get_filter_value("to_date")) {
					report.set_filter_value("to_date", to_date);
				} else {
					report.refresh();
				}
			},
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "submitted_by",
			label: __("Submitted By"),
			fieldtype: "MultiSelectList",
			get_data: (txt) =>
				frappe.xcall(
					"frappe_agile.frappe_agile.report.sprint_retro_report.sprint_retro_report.submitted_by_options",
					{ txt }
				),
		},
	],
};
