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
	onload: function(listview) {
		listenForKanbanCardClicks(listview);
	},
	refresh: function(listview) {
		setupKanbanFilters(listview);
		listenForKanbanCardClicks(listview);
	},
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

function listenForKanbanCardClicks(listview) {
	// Delegated listener to open kanban cards in a new tab
	if (!listview.$page || listview.view_name !== "Kanban") return;
	
	listview.$page.off('click.kanban_new_tab');
	listview.$page.on('click.kanban_new_tab', '.kanban-card', function (e) {
		// If clicking a meta button (like/comment heart), do not intercept so natively handled actions persist
		if ($(e.target).closest('.kanban-card-meta').length > 0) return;

		e.preventDefault();
		e.stopPropagation();
		
		// The DocName is stored natively in a URI encoded attribute explicitly on the outer .kanban-card-wrapper layout
		let docName = $(this).closest('.kanban-card-wrapper').attr('data-name');
		
		if (docName) {
			docName = decodeURIComponent(docName);
			const url = frappe.urllib.get_full_url('/app/work-item/' + encodeURIComponent(docName));
			window.open(url, '_blank');
		}
	});
}

function setupKanbanFilters(listview) {
	// Only render custom static filter bar on Kanban Views
	if (listview.view_name !== "Kanban") {
		if (listview.$custom_kanban_filters) {
			listview.$custom_kanban_filters.hide();
		}
		return;
	}
	
	if (!listview.$custom_kanban_filters) {
		// Create the horizontal flex layout container and append dynamically under the page-head
		listview.$custom_kanban_filters = $('<div class="custom-kanban-filters" style="display: flex; gap: 15px; padding: 10px 15px; border-bottom: 1px solid var(--border-color); background: var(--bg-color);"></div>');
		listview.$page.find('.layout-main-section').prepend(listview.$custom_kanban_filters);

		// Store references to the controls for syncing and updates
		listview.custom_filter_controls = {};

		let filters_to_add = [
			{ fieldname: 'sprint', fieldtype: 'Link', options: 'Sprint', label: __('Sprint'), placeholder: __('Sprint') },
			{ fieldname: 'epic', fieldtype: 'Link', options: 'Work Item', label: __('Epic'), placeholder: __('Epic') },
			{ fieldname: 'assignee_user', fieldtype: 'Link', options: 'User', label: __('Assignee'), placeholder: __('Assignee') }
		];

		filters_to_add.forEach(df => {
			let control = frappe.ui.form.make_control({
				df: Object.assign({}, df, {
					onchange: function() {
						let val = control.get_value();
						
						// Force purge from Frappe's global route_options memory which natively resurrects filters on refresh
						if (frappe.route_options && frappe.route_options[df.fieldname]) {
							delete frappe.route_options[df.fieldname];
						}

						// Retrieve all currently active filters across the board
						let current_filters = listview.filter_area.get() || [];
						// Filter out any existing conditions for THIS specific custom field
						let updated_filters = current_filters.filter(f => f[1] !== df.fieldname);
						
						// Completely wipe Frappe's inner filter layout engine natively
						listview.filter_area.clear();
						
						if (val) {
							updated_filters.push(['Work Item', df.fieldname, '=', val]);
						}
						
						if (updated_filters.length > 0) {
							// Push the newly cleaned stack back into the UI (auto-triggers data refresh)
							listview.filter_area.add(updated_filters);
						} else {
							// If literally zero filters remain, manually execute the data refresh!
							listview.refresh();
						}
					}
				}),
				parent: listview.$custom_kanban_filters,
				only_input: true
			});
			control.make_input();
			control.$wrapper.css({'min-width': '180px', 'margin-bottom': '0'});
			listview.custom_filter_controls[df.fieldname] = control;
		});
	} else {
		// Existing bar is cached, just show it
		listview.$custom_kanban_filters.show();
	}

	// Always synchronize the custom inputs with currently active Frappe filters 
	// (handles when user toggled from List view with active filters into Kanban)
	if (listview.custom_filter_controls) {
		let current_filters = listview.filter_area.get();
		Object.keys(listview.custom_filter_controls).forEach(fieldname => {
			let active_filter = current_filters.find(f => f[1] === fieldname);
			let target_val = active_filter ? active_filter[3] : '';
			let control = listview.custom_filter_controls[fieldname];
			if (control.get_value() !== target_val) {
				control.set_value(target_val);
			}
		});
	}

	// Suppress the distracting "Not Saved" indicator when dynamically filtering
	if (listview.view_name === "Kanban") {
		listview.on_filter_change = function() {
			listview.page.clear_indicator();
		};
		// Clear it immediately in case it was already set by Frappe's initialization
		listview.page.clear_indicator();
	}
}
