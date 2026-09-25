// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

const WEDNESDAY = 3;

frappe.ui.form.on("Sprint Retro", {
	onload(frm) {
		if (frm.is_new() && frm.doc.to_date && !frm.doc.from_date) {
			frm.set_value("from_date", get_last_wednesday(frm.doc.to_date));
		}
	},

	from_date(frm) {
		if (frm.doc.from_date) {
			frm.set_value("to_date", frappe.datetime.add_days(frm.doc.from_date, 6));
		}
	},
});

function get_last_wednesday(date) {
	const days_back = (frappe.datetime.str_to_obj(date).getDay() - WEDNESDAY + 7) % 7 || 7;
	return frappe.datetime.add_days(date, -days_back);
}
