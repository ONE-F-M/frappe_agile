# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""
Unit tests for frappe_agile.api.github_sync

Run with:
	bench --site onefm run-tests --app frappe_agile \
		--module frappe_agile.api.test_github_sync
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_agile.api import github_sync

ORG_REPOS = "processa.agents_sandbox.customization.github_sync.org_repos"
_real_get_cached_doc = frappe.get_cached_doc


def _settings_with_token(token):
	settings = MagicMock()
	settings.get_password.return_value = token

	def get_cached_doc(doctype, *args, **kwargs):
		if doctype == "Processa Settings":
			return settings
		return _real_get_cached_doc(doctype, *args, **kwargs)

	return patch("frappe.get_cached_doc", side_effect=get_cached_doc)


class TestSyncGithubRepositories(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._created = []

	def tearDown(self):
		for name in self._created:
			frappe.delete_doc("GitHub Repository", name, force=True, ignore_permissions=True, ignore_missing=True)
		super().tearDown()

	def test_new_repos_are_created(self):
		repos = [
			{"name": "_test_repo_a", "description": "desc a", "html_url": "https://github.com/ONE-F-M/_test_repo_a"},
			{"name": "_test_repo_b", "description": "", "html_url": "https://github.com/ONE-F-M/_test_repo_b"},
		]
		self._created += ["_test_repo_a", "_test_repo_b"]
		with _settings_with_token("tok"), patch(ORG_REPOS, return_value=repos) as org_repos:
			summary = github_sync.sync_github_repositories()

		org_repos.assert_called_once_with("tok", "ONE-F-M")
		self.assertEqual(summary, {"created": 2, "updated": 0, "total": 2})
		doc = frappe.get_doc("GitHub Repository", "_test_repo_a")
		self.assertEqual(doc.description, "desc a")
		self.assertEqual(doc.html_url, "https://github.com/ONE-F-M/_test_repo_a")
		self.assertIsNotNone(doc.synced_on)

	def test_existing_repos_are_updated_not_duplicated(self):
		frappe.get_doc({
			"doctype": "GitHub Repository", "repo_name": "_test_repo_a",
			"description": "stale", "html_url": "https://old",
		}).insert(ignore_permissions=True)
		self._created.append("_test_repo_a")

		repos = [{"name": "_test_repo_a", "description": "fresh", "html_url": "https://new"}]
		with _settings_with_token("tok"), patch(ORG_REPOS, return_value=repos):
			summary = github_sync.sync_github_repositories()

		self.assertEqual(summary, {"created": 0, "updated": 1, "total": 1})
		self.assertEqual(frappe.db.count("GitHub Repository", {"repo_name": "_test_repo_a"}), 1)
		doc = frappe.get_doc("GitHub Repository", "_test_repo_a")
		self.assertEqual(doc.description, "fresh")
		self.assertEqual(doc.html_url, "https://new")

	def test_empty_org_result_is_a_no_op(self):
		with _settings_with_token("tok"), patch(ORG_REPOS, return_value=[]):
			summary = github_sync.sync_github_repositories()
		self.assertEqual(summary, {"created": 0, "updated": 0, "total": 0})

	def test_missing_token_throws_without_calling_github(self):
		with _settings_with_token(""), patch(ORG_REPOS) as org_repos:
			with self.assertRaises(frappe.ValidationError):
				github_sync.sync_github_repositories()
		org_repos.assert_not_called()
