frappe.ui.form.on("Sprint", {
	refresh(frm) {
		frm.set_df_property("expected_velocity", "description",
			__("Auto-calculated as the sum of Story Points of all linked Work Items."));

		// Story 6: Lock completed sprint forms client-side
		if (frm.doc.status === "Completed" && !frm.is_new()) {
			frm.disable_form();
		}
	},

	validate: function(frm) {
		// Only intercept when transitioning to Completed on an existing saved document
		if (frm.doc.status === "Completed" && !frm.is_new() && !frm.doc._modal_confirmed) {
			
			// Block the native save immediately
			frappe.validated = false;

			// Fetch all Work Items linked to this sprint to determine incomplete ones
			frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Work Item",
					filters: { sprint: frm.doc.name, workflow_state: ["!=", "Done"] },
					fields: ["name", "title"],
					limit_page_length: 0
				},
				callback: function (r) {
					let incomplete = r.message || [];

					if (incomplete.length === 0) {
						// Scenario A: All work items are Done — simple completion dialog
						let d = new frappe.ui.Dialog({
							title: __("Complete Sprint"),
							fields: [
								{
									fieldtype: "HTML",
									options: `<p>${__("All work items are done. Complete this sprint?")}</p>`
								}
							],
							primary_action_label: __("Complete Sprint"),
							primary_action: function () {
								d.hide();
								_trigger_save(frm);
							},
							secondary_action_label: __("Complete & Create New Sprint"),
							secondary_action: function () {
								d.hide();
								_trigger_save(frm, true);
							}
						});
						d.show();
					} else {
						// Scenario B: Some work items are not Done — ask where to move them
						let d = new frappe.ui.Dialog({
							title: __("Incomplete Work Items"),
							fields: [
								{
									fieldtype: "HTML",
									options: `<p><b>${frm.doc.name}</b> ${__("has")} <b>${incomplete.length}</b> ${__("incomplete work item(s). Where should they go?")}</p>`
								},
								{
									fieldname: "move_to",
									fieldtype: "Select",
									label: __("Move incomplete items to"),
									options: "Move to Backlog\nMove to New Sprint",
									default: "Move to Backlog",
									reqd: 1
								}
							],
							primary_action_label: __("Confirm & Complete"),
							primary_action: function (values) {
								frappe.call({
									method: "frappe_agile.frappe_agile.doctype.sprint.sprint.handle_incomplete_items",
									args: {
										sprint: frm.doc.name,
										action: values.move_to
									},
									callback: function () {
										d.hide();
										_trigger_save(frm);
									}
								});
							}
						});
						d.show();
					}
				}
			});
		}
		
		// Ensure standard Frappe script pipeline evaluates synchronously to TRUE
		return true;
	}
});

function _trigger_save(frm, create_next) {
	frm.doc._modal_confirmed = true;
	frappe.validated = true;
	frm.save().then(() => {
		if (create_next) {
			frappe.db.insert({
				doctype: "Sprint",
				sprint_prefix: frm.doc.sprint_prefix,
				project: frm.doc.project,
				status: "Draft"
			}).then((new_doc) => {
				frappe.set_route("Form", "Sprint", new_doc.name);
			});
		} else {
			frm.reload_doc();
		}
	});
}
