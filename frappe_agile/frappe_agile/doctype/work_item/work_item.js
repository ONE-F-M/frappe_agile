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

		// Sprint is deliberately unfiltered — every Sprint is offered regardless of
		// status or project. _validate_sprint_status() in work_item.py is the single
		// source of truth for which Sprints a Work Item may actually be saved against.

		apply_project_user_filters(frm);
	},

	project: function (frm) {
		// The offered users depend on the project, and setup ran before it was
		// picked — so the filter has to be built again whenever it changes.
		apply_project_user_filters(frm);
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

	work_item_type: function (frm) {
		// Clear epic, sprint and orchestrator fields when type switches to Epic.
		// _validate_orchestrator_target() in work_item.py rejects an orchestrator
		// Epic on save; clearing it here means the user never reaches that error.
		if (frm.doc.work_item_type === "Epic") {
			frm.set_value("epic", null);
			frm.set_value("sprint", null);
			frm.set_value("orchestrator", 0);
		}
	},

});

// Offer Assignee User and PR Reviewer User only to the users on the item's
// project. Without a project yet, to anyone who is on some project.
function apply_project_user_filters(frm) {
	frappe.call({
		method: "frappe_agile.frappe_agile.doctype.work_item.work_item.get_assignable_users",
		args: { project: frm.doc.project || "" },
		callback: function (r) {
			const users = r.message || [];
			const query = function () {
				return {
					filters: {
						name: ["in", users],
					},
				};
			};
			frm.set_query("assignee_user", query);
			frm.set_query("pr_reviewer_user", query);

			if (users.length) {
				return;
			}
			// An empty list is a configuration gap, not a state to puzzle over —
			// name the place to fix.
			const message = frm.doc.project
				? __("Project {0} has no users. Add them in its Users table to enable Assignee and PR Reviewer selection.", [
						`<a href="/app/project/${encodeURIComponent(frm.doc.project)}">${frappe.utils.escape_html(frm.doc.project)}</a>`,
				  ])
				: __("No project has any users yet. Add users to a project to enable Assignee and PR Reviewer selection.");
			frappe.show_alert({ message: message, indicator: "orange" }, 10);
		},
	});
}
