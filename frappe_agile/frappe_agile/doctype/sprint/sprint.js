frappe.ui.form.on("Sprint", {
	refresh(frm) {
		frm.set_df_property("expected_velocity", "description",
			__("Auto-calculated as the sum of Story Points of all linked Work Items."));
	}
});
