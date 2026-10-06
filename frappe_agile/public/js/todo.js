// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

// ---------------------------------------------------------------------------
// ToDo — Form customisation
// ---------------------------------------------------------------------------
// Registered via hooks.py → doctype_js["ToDo"]
//
// Responsibilities:
//   1. Show a placeholder hint in the description field when the form loads

frappe.ui.form.on("ToDo", {
	onload(frm) {
		frm.set_df_property("description", "placeholder", __("What needs doing?"));
	},
});
