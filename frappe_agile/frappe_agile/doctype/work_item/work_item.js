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
			return {
				filters: {
					project: frm.doc.project || undefined,
				},
			};
		};
	},

	project: function (frm) {
		// Clear sprint when project changes (avoid mismatched sprint)
		frm.set_value("sprint", null);

		// Re-apply sprint filter for new project
		frm.fields_dict.sprint.get_query = function () {
			return {
				filters: {
					project: frm.doc.project || undefined,
				},
			};
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
