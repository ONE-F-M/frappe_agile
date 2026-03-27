// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

// ---------------------------------------------------------------------------
// Work Item — List View customisation
// ---------------------------------------------------------------------------
// Registered via hooks.py → doctype_list_js["Work Item"]
//
// Responsibilities:
//   1. Handle row click new-tab routing and badge styling for Work Item Type 
//   2. Note: "Backlog" filter behavior is natively handled by standard Frappe 
//      List Filter DocType managed in setup.py

frappe.listview_settings["Work Item"] = {
	add_fields: [
		"title",
		"work_item_type",
		"workflow_state",
		"story_points",
		"assignee_name"
	],

	on_row_click: function () {
		// Handled via name formatter — opens in new tab.
	},

	formatters: {
		// Open Work Item in a new tab on ID click
		name: function (value, field, doc) {
			if (!value) return "";
			const url = "/app/work-item/" + encodeURIComponent(value);
			return `<a href="${url}" target="_blank" rel="noopener noreferrer"
			         onclick="event.stopPropagation()"
			         class="font-weight-bold">${frappe.utils.escape_html(value)}</a>`;
		},

		// Colored indicator pill for Work Item Type (Frappe v15 classes)
		work_item_type: function (value) {
			if (!value) return "";
			const color_map = {
				"Epic": "purple",
				"User Story": "blue",
				"Task": "green",
				"Bug": "red",
			};
			const color = color_map[value] || "grey";
			return `<span class="indicator-pill ${color}">${frappe.utils.escape_html(__(value))}</span>`;
		}
	},
};



