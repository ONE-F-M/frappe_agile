# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

"""Who may review a Work Item's pull request.

The Development Team in Frappe Agile Settings is the list, wherever the work
came from. The GitHub webhook already resolves an incoming reviewer through that
same table — `set_pr_reviewer` matches the reviewer's GitHub login against
`Development Team Member.github_username` — so a picker offering anyone else
offers names the webhook can never write, and hides the ones it does.

This file is deliberately identical on every branch: the reviewer's list is the
one thing about these pickers that does not differ between them.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_agile.frappe_agile.doctype.frappe_agile_settings.frappe_agile_settings import (
	get_development_team_users,
)

PREFIX = "_Test Reviewer"
_stem = PREFIX.lower().replace(" ", ".")
ON_TEAM = f"{_stem}.on.team@example.com"
OFF_TEAM = f"{_stem}.off.team@example.com"


class TestPRReviewerSelection(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for email in (ON_TEAM, OFF_TEAM):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{"doctype": "User", "email": email, "first_name": email.split("@")[0]}
				).insert(ignore_permissions=True)

		settings = frappe.get_single("Frappe Agile Settings")
		cls.original_team = [row.user for row in settings.development_team if row.user]
		settings.set("development_team", [])
		settings.append("development_team", {"user": ON_TEAM})
		settings.save(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		settings = frappe.get_single("Frappe Agile Settings")
		settings.set("development_team", [])
		for email in cls.original_team:
			settings.append("development_team", {"user": email})
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def test_the_reviewers_are_the_development_team(self):
		self.assertEqual(get_development_team_users(), [ON_TEAM])

	def test_someone_off_the_team_is_not_a_reviewer(self):
		self.assertNotIn(OFF_TEAM, get_development_team_users())

	def test_an_empty_team_offers_nobody(self):
		"""Nobody, rather than everybody: an empty team is a gap to fill."""
		settings = frappe.get_single("Frappe Agile Settings")
		settings.set("development_team", [])
		settings.save(ignore_permissions=True)
		try:
			self.assertEqual(get_development_team_users(), [])
		finally:
			settings.append("development_team", {"user": ON_TEAM})
			settings.save(ignore_permissions=True)
