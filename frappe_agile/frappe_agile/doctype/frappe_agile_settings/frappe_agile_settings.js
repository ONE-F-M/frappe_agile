// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

frappe.ui.form.on("Frappe Agile Settings", {
	refresh(frm) {
		// Manual only, no scheduled job — target_app's repo picker (GitHub
		// Repository) only ever reflects the org as of the last click here.
		frm.add_custom_button(__("Sync GitHub Repositories"), () => {
			frappe.call({
				method: "frappe_agile.api.github_sync.sync_github_repositories",
				freeze: true,
				freeze_message: __("Fetching repositories from GitHub..."),
			}).then((r) => {
				const summary = r.message || {};
				frappe.msgprint(
					__("Synced {0} repositories ({1} new, {2} updated).", [
						summary.total ?? 0,
						summary.created ?? 0,
						summary.updated ?? 0,
					])
				);
			});
		}, __("GitHub Integration"));
	},
});
