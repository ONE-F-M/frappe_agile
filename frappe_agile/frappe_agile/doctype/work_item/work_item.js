// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

frappe.ui.form.on("Work Item", {
	// Filter Epic link field to only show Work Items of type 'Epic'
	epic: function (frm) {
		frm.fields_dict.epic.get_query = function () {
			return {
				filters: {
					work_item_type: "Epic",
				},
			};
		};
	},

	setup: function (frm) {
		frm.set_query("work_item_template", function () {
			return {
				filters: {
					disabled: 0,
				},
			};
		});

		// Filter sprint to only active sprints, scoped to the selected project
		frm.set_query("sprint", function () {
			let filters = { status: "Active" };
			if (frm.doc.project) {
				filters.project = frm.doc.project;
			}
			return { filters: filters };
		});

		// Filter Assignee User and PR Reviewer User to Development Team members
		frappe.call({
			method:
				"frappe_agile.frappe_agile.doctype.frappe_agile_settings.frappe_agile_settings.get_development_team_users",
			async: false,
			callback: function (r) {
				if (r.message && r.message.length > 0) {
					const team_users = r.message;

					frm.set_query("assignee_user", function () {
						return {
							filters: {
								name: ["in", team_users],
							},
						};
					});

					frm.set_query("pr_reviewer_user", function () {
						return {
							filters: {
								name: ["in", team_users],
							},
						};
					});
				}
			},
		});
	},

	onload: function (frm) {
		if (frm.is_new() && !frm.doc.work_item_template) {
			frappe.db.get_value("Work Item Template", { default_template: 1, disabled: 0 }, "name").then(r => {
				if (r && r.message && r.message.name) {
					// This automatically triggers the work_item_template change handler
					frm.set_value("work_item_template", r.message.name);
				}
			});
		}
	},

	work_item_template: function (frm) {
		if (frm.doc.work_item_template) {
			frappe.db.get_value("Work Item Template", frm.doc.work_item_template, "description").then(r => {
				if (r && r.message && r.message.description) {
					frm.set_value("description", r.message.description);
				}
			});
		}
	},

	refresh: function (frm) {
		// Apply epic filter on form load too
		frm.fields_dict.epic.get_query = function () {
			return {
				filters: {
					work_item_type: "Epic",
				},
			};
		};
	},

	project: function (frm) {
		// Clear sprint when project changes (avoid mismatched sprint)
		frm.set_value("sprint", null);
	},

	work_item_type: function (frm) {
		// Clear epic and sprint fields when type switches to Epic
		if (frm.doc.work_item_type === "Epic") {
			frm.set_value("epic", null);
			frm.set_value("sprint", null);
		}
	},
});
