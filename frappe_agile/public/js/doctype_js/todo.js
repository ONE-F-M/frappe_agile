frappe.ui.form.on("ToDo", {
	onload: function (frm) {
		frm.set_df_property("description", "placeholder", "What needs doing?");
	},
});
