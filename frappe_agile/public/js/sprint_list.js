// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

// ---------------------------------------------------------------------------
// Sprint — List View customisation
// ---------------------------------------------------------------------------
// Registered via hooks.py → doctype_list_js["Sprint"]
//
// Responsibilities:
//   1. Provide inline filters for Status, Start Date, and End Date

frappe.listview_settings["Sprint"] = {
	onload: function (listview) {},
	refresh: function (listview) {
		setupSprintListFilters(listview);
	},
};

function setupSprintListFilters(listview) {
	// Only render custom inline filter bar on List views
	if (listview.view_name !== "List") {
		if (listview.$custom_sprint_filters) {
			listview.$custom_sprint_filters.hide();
		}
		return;
	}

	if (!listview.$custom_sprint_filters) {
		listview.$custom_sprint_filters = $(
			'<div class="custom-sprint-filters" style="display: flex; gap: 15px; padding: 10px 15px; border-bottom: 1px solid var(--border-color); background: var(--bg-color);"></div>'
		);
		listview.$page
			.find(".layout-main-section")
			.prepend(listview.$custom_sprint_filters);

		listview.custom_sprint_controls = {};

		// Derive Status options from DocType meta
		const status_options =
			frappe.meta.get_docfield("Sprint", "status")?.options ||
			"\nDraft\nActive\nCompleted";

		let filters_to_add = [
			{
				fieldname: "status",
				fieldtype: "Select",
				options: status_options,
				label: __("Status"),
				placeholder: __("Status"),
				operator: "=",
			},
			{
				fieldname: "start_date",
				fieldtype: "Date",
				label: __("Start Date"),
				placeholder: __("Start Date (from)"),
				operator: ">=",
			},
			{
				fieldname: "end_date",
				fieldtype: "Date",
				label: __("End Date"),
				placeholder: __("End Date (up to)"),
				operator: "<=",
			},
		];

		filters_to_add.forEach(function (df) {
			let operator = df.operator;
			let control = frappe.ui.form.make_control({
				df: Object.assign({}, df, {
					onchange: function () {
						if (control.is_syncing) return;

						let val = control.get_value();

						if (
							frappe.route_options &&
							frappe.route_options[df.fieldname]
						) {
							delete frappe.route_options[df.fieldname];
						}

						let current_filters =
							listview.filter_area.get() || [];
						// Remove only the filter this control manages
						let updated_filters = current_filters.filter(
							function (f) {
								return !(
									f[1] === df.fieldname &&
									f[2] === operator
								);
							}
						);
						listview.filter_area.clear();

						if (val) {
							updated_filters.push([
								"Sprint",
								df.fieldname,
								operator,
								val,
							]);
						}

						if (updated_filters.length > 0) {
							listview.filter_area.add(updated_filters);
						} else {
							listview.refresh();
						}
					},
				}),
				parent: listview.$custom_sprint_filters,
				only_input: true,
			});
			control.make_input();

			control.$wrapper.css({
				"min-width": "20%",
				"margin-bottom": "0",
				flex: "1",
			});
			listview.custom_sprint_controls[df.fieldname] = control;
			// Stash operator on the control for sync lookups
			control._filter_operator = operator;
		});
	} else {
		listview.$custom_sprint_filters.show();
	}

	// Sync control values from active URL / sidebar filters
	if (listview.custom_sprint_controls) {
		let current_filters = listview.filter_area.get();
		Object.keys(listview.custom_sprint_controls).forEach(function (
			fieldname
		) {
			let control = listview.custom_sprint_controls[fieldname];
			let op = control._filter_operator;
			let active_filter = current_filters.find(function (f) {
				return f[1] === fieldname && f[2] === op;
			});
			let target_val = active_filter ? active_filter[3] : "";

			if (control.get_value() !== target_val) {
				control.is_syncing = true;
				let promise = control.set_value(target_val);
				if (promise && promise.finally) {
					promise.finally(function () {
						control.is_syncing = false;
					});
				} else {
					control.is_syncing = false;
				}
			}
		});
	}

	listview.on_filter_change = function () {
		listview.page.clear_indicator();
	};
	listview.page.clear_indicator();
}
