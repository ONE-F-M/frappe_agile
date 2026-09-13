# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""Sync GitHub Repository records from the ONE-F-M org, so Work Item's
target_app Link field always offers whatever repos actually exist instead
of a hardcoded list that drifts the moment a new one is created.

frappe_agile has no GitHub credential of its own — this calls one_bpmn's
list_org_repos (a plain Python call, both apps share one site/process),
which resolves the token already configured on Processa Settings for the
Dev Agent sandbox, rather than a second token existing purely to duplicate
it. Manual only ("Sync GitHub Repositories" button on Frappe Agile
Settings) — no scheduled job.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime


@frappe.whitelist()
def sync_github_repositories() -> dict:
	"""Upsert one GitHub Repository row per repo in the ONE-F-M org.

	Returns a summary dict (created/updated counts) so the calling button
	can tell a person something happened, not just "done"."""
	from one_bpmn.api.github_sync import list_org_repos

	repos = list_org_repos()
	synced_on = now_datetime()

	created = 0
	updated = 0
	for repo in repos:
		name = repo["name"]
		if frappe.db.exists("GitHub Repository", name):
			doc = frappe.get_doc("GitHub Repository", name)
			updated += 1
		else:
			doc = frappe.new_doc("GitHub Repository")
			doc.repo_name = name
			created += 1
		doc.description = repo.get("description") or ""
		doc.html_url = repo.get("html_url") or ""
		doc.synced_on = synced_on
		doc.save(ignore_permissions=True)

	frappe.db.commit()
	return {"created": created, "updated": updated, "total": len(repos)}
