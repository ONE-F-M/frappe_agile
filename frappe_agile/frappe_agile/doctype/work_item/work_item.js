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
			callback: function (r) {
				const team_users = r.message || [];

				if (team_users.length > 0) {
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
				} else {
					// No Development Team configured — restrict selection and notify
					const empty_filter = function () {
						return {
							filters: {
								name: ["in", []],
							},
						};
					};
					frm.set_query("assignee_user", empty_filter);
					frm.set_query("pr_reviewer_user", empty_filter);

					frappe.show_alert({
						message: __("Please configure the Development Team in {0} to enable Assignee and PR Reviewer selection.", [
							'<a href="/app/frappe-agile-settings">Frappe Agile Settings</a>'
						]),
						indicator: "orange",
					}, 10);
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

		// Render PR Link as a clickable hyperlink that opens in a new tab
		const pr_field = frm.fields_dict.pr_link;
		if (pr_field && pr_field.$wrapper) {
			// Always remove stale button (handles field being cleared)
			pr_field.$wrapper.find(".pr-link-open").remove();

			if (frm.doc.pr_link) {
				// Only render for safe URL schemes (http / https)
				let is_safe = false;
				try {
					const parsed = new URL(frm.doc.pr_link);
					is_safe = ["http:", "https:"].includes(parsed.protocol);
				} catch (e) {
					// malformed URL — do not render
				}

				if (is_safe) {
					const $wrapper = $("<div>").addClass("pr-link-open mt-1");
					const $anchor = $("<a>")
						.addClass("btn btn-xs btn-default")
						.attr("href", frm.doc.pr_link)
						.attr("target", "_blank")
						.attr("rel", "noopener noreferrer")
						.text(__("Open PR") + " ↗");
					$wrapper.append($anchor);
					pr_field.$wrapper.append($wrapper);
				}
			}
		}

		// Add "Add Rejection Note" button when in Rejected state
		if (frm.doc.workflow_state === "Rejected") {
			frm.add_custom_button(__("Add Rejection Note"), function () {
				frappe.prompt(
					[
						{
							label: __("Reason for Rejection"),
							fieldname: "reason",
							fieldtype: "Small Text",
							reqd: 1,
						},
					],
					(values) => {
						const row = frm.add_child("rejection_notes");
						row.date = frappe.datetime.get_today();
						row.reason_for_rejection = values.reason;
						frm.refresh_field("rejection_notes");
						frm.save();
					},
					__("Add Rejection Note"),
					__("Add")
				);
			});
		}
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
