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
		setupListViewFilters(listview);
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
		// If clicking a meta button (like/comment heart), do not intercept
		if ($(e.target).closest('.kanban-card-meta').length > 0) return;

		e.preventDefault();
		e.stopPropagation();
		
		let docName = $(this).closest('.kanban-card-wrapper').attr('data-name');
		if (docName) {
			docName = decodeURIComponent(docName);
			const url = frappe.urllib.get_full_url('/app/work-item/' + encodeURIComponent(docName));
			window.open(url, '_blank');
		}
	});
}

function setupListViewFilters(listview) {
	// Only render custom inline filter bar on List Views
	if (listview.view_name !== "List") {
		if (listview.$custom_list_filters) {
			listview.$custom_list_filters.hide();
		}
		return;
	}

	if (!listview.$custom_list_filters) {
		listview.$custom_list_filters = $('<div class="custom-list-filters" style="display: flex; gap: 15px; padding: 10px 15px; border-bottom: 1px solid var(--border-color); background: var(--bg-color);"></div>');
		listview.$page.find('.layout-main-section').prepend(listview.$custom_list_filters);

		listview.custom_list_controls = {};

		// Exclude "Epic" from the Work Item Type filter — only show User Story, Task, Bug
		const type_options = "\nUser Story\nTask\nBug";
		const status_options = frappe.meta.get_docfield("Work Item", "status") ? frappe.meta.get_docfield("Work Item", "status").options : "\nOpen\nIn Progress\nDone";

		let filters_to_add = [
			{ fieldname: 'work_item_type', fieldtype: 'Select', options: type_options, label: __('Work Item Type'), placeholder: __('Work Item Type') },
			{ fieldname: 'status', fieldtype: 'Select', options: status_options, label: __('Status'), placeholder: __('Status') },
			{ fieldname: 'sprint', fieldtype: 'Link', options: 'Sprint', label: __('Sprint'), placeholder: __('Sprint') },
			{ fieldname: 'assignee_user', fieldtype: 'Link', options: 'User', label: __('Assignee User'), placeholder: __('Assignee User') }
		];

		filters_to_add.forEach(df => {
			let control = frappe.ui.form.make_control({
				df: Object.assign({}, df, {
					onchange: function() {
						if (control.is_syncing) return;

						let val = control.get_value();
						
						if (frappe.route_options && frappe.route_options[df.fieldname]) {
							delete frappe.route_options[df.fieldname];
						}

						let current_filters = listview.filter_area.get() || [];
						// Only ever remove '=' filters created by this control, leave complex saved filters like '!=' or 'not in' alone!
						let updated_filters = current_filters.filter(f => !(f[1] === df.fieldname && f[2] === '='));
						listview.filter_area.clear();
						
						if (val) {
							updated_filters.push(['Work Item', df.fieldname, '=', val]);
						}
						
						if (updated_filters.length > 0) {
							listview.filter_area.add(updated_filters);
						} else {
							listview.refresh();
						}
					}
				}),
				parent: listview.$custom_list_filters,
				only_input: true
			});
			control.make_input();
			
			control.$wrapper.css({'min-width': '20%', 'margin-bottom': '0', 'flex': '1'});
			listview.custom_list_controls[df.fieldname] = control;
		});
	} else {
		listview.$custom_list_filters.show();
	}

	if (listview.custom_list_controls) {
		let current_filters = listview.filter_area.get();
		Object.keys(listview.custom_list_controls).forEach(fieldname => {
			// This inline UI can only represent simple '=' queries.
			let active_filter = current_filters.find(f => f[1] === fieldname && f[2] === '=');
			let target_val = active_filter ? active_filter[3] : '';
			let control = listview.custom_list_controls[fieldname];
			
			if (control.get_value() !== target_val) {
				control.is_syncing = true;
				let promise = control.set_value(target_val);
				if (promise && promise.finally) {
					promise.finally(() => { control.is_syncing = false; });
				} else {
					control.is_syncing = false;
				}
			}
		});
	}

	listview.on_filter_change = function() {
		listview.page.clear_indicator();
	};
	listview.page.clear_indicator();
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
		listview.$custom_kanban_filters = $('<div class="custom-kanban-filters" style="display: flex; gap: 15px; padding: 10px 15px; border-bottom: 1px solid var(--border-color); background: var(--bg-color);"></div>');
		listview.$page.find('.layout-main-section').prepend(listview.$custom_kanban_filters);

		listview.custom_kanban_controls = {};

		let filters_to_add = [
			{ fieldname: 'sprint', fieldtype: 'Link', options: 'Sprint', label: __('Sprint'), placeholder: __('Sprint'),
				get_query: function() { return { filters: { "status": "Active" } }; }
			},
			{ fieldname: 'epic', fieldtype: 'Link', options: 'Work Item', label: __('Epic'), placeholder: __('Epic') },
			{ fieldname: 'assignee_user', fieldtype: 'Link', options: 'User', label: __('Assignee'), placeholder: __('Assignee') }
		];

		filters_to_add.forEach(df => {
			let control = frappe.ui.form.make_control({
				df: Object.assign({}, df, {
					onchange: function() {
						if (control.is_syncing) return;

						let val = control.get_value();
						
						if (frappe.route_options && frappe.route_options[df.fieldname]) {
							delete frappe.route_options[df.fieldname];
						}

						let current_filters = listview.filter_area.get() || [];
						let updated_filters = current_filters.filter(f => !(f[1] === df.fieldname && f[2] === '='));
						
						listview.filter_area.clear();
						
						if (val) {
							updated_filters.push(['Work Item', df.fieldname, '=', val]);
						}
						
						if (updated_filters.length > 0) {
							listview.filter_area.add(updated_filters);
						} else {
							listview.refresh();
						}
					}
				}),
				parent: listview.$custom_kanban_filters,
				only_input: true
			});
			control.make_input();
			control.$wrapper.css({'min-width': '180px', 'margin-bottom': '0'});
			listview.custom_kanban_controls[df.fieldname] = control;
		});
	} else {
		listview.$custom_kanban_filters.show();
	}

	if (listview.custom_kanban_controls) {
		let current_filters = listview.filter_area.get();
		Object.keys(listview.custom_kanban_controls).forEach(fieldname => {
			let active_filter = current_filters.find(f => f[1] === fieldname && f[2] === '=');
			let target_val = active_filter ? active_filter[3] : '';
			let control = listview.custom_kanban_controls[fieldname];
			
			if (control.get_value() !== target_val) {
				control.is_syncing = true;
				let promise = control.set_value(target_val);
				if (promise && promise.finally) {
					promise.finally(() => { control.is_syncing = false; });
				} else {
					control.is_syncing = false;
				}
			}
		});
	}

	if (listview.view_name === "Kanban") {
		listview.on_filter_change = function() {
			listview.page.clear_indicator();
		};
		listview.page.clear_indicator();
	}
}
