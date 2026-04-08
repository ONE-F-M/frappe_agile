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

		// Filter Project to only show SCRUM projects
		frm.set_query("project", function () {
			return {
				filters: {
					project_type: "SCRUM Project",
				},
			};
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

		// Filter sprint to only sprints matching the selected project
		frm.fields_dict.sprint.get_query = function () {
			let filters = { status: ["!=", "Completed"] };
			if (frm.doc.project) {
				filters.project = frm.doc.project;
			}
			return { filters: filters };
		};
	},

	project: function (frm) {
		// Clear sprint when project changes (avoid mismatched sprint)
		frm.set_value("sprint", null);

		// Re-apply sprint filter for new project
		frm.fields_dict.sprint.get_query = function () {
			let filters = { status: ["!=", "Completed"] };
			if (frm.doc.project) {
				filters.project = frm.doc.project;
			}
			return { filters: filters };
		};
	},

	work_item_type: function (frm) {
		// Clear epic and sprint fields when type switches to Epic
		if (frm.doc.work_item_type === "Epic") {
			frm.set_value("epic", null);
			frm.set_value("sprint", null);
		}
	},
});
