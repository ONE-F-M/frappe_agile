# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

"""Who a Work Item may be assigned to, and who may review its PR.

Assigning: the project's Users table is the one list. The Development Team in
Frappe Agile Settings used to be the standing list that a project could only
narrow, so a project member who was not also on the team could never be
assigned; it plays no part in assigning now. Without a project to go by the
answer is everyone on any project, because whoever is assigned has to be on the
project the item belongs to.

Reviewing is the other way round: it is the Development Team's job wherever the
work came from, and the GitHub webhook already resolves a reviewer through that
table, so the picker has to offer what the webhook can write.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_agile.frappe_agile.doctype.frappe_agile_settings.frappe_agile_settings import (
	get_development_team_users,
)
from frappe_agile.frappe_agile.doctype.work_item.work_item import get_assignable_users

PREFIX = "_Test Assignee"
_stem = PREFIX.lower().replace(" ", ".")
ON_ALPHA = f"{_stem}.on.alpha@example.com"
ON_BOTH = f"{_stem}.on.both@example.com"
ON_BETA = f"{_stem}.on.beta@example.com"
ON_TEAM_ONLY = f"{_stem}.team.only@example.com"


class TestAssigneeSelection(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for email in (ON_ALPHA, ON_BOTH, ON_BETA, ON_TEAM_ONLY):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{"doctype": "User", "email": email, "first_name": email.split("@")[0]}
				).insert(ignore_permissions=True)

		# Someone on the Development Team and on no project: if the team still
		# had a say, this person would show up.
		cls.settings = frappe.get_single("Frappe Agile Settings")
		cls.original_team = [row.user for row in cls.settings.development_team]
		cls.settings.set("development_team", [])
		cls.settings.append("development_team", {"user": ON_TEAM_ONLY})
		cls.settings.save(ignore_permissions=True)

		cls.alpha = cls._project("Alpha", [ON_ALPHA, ON_BOTH])
		cls.beta = cls._project("Beta", [ON_BETA, ON_BOTH])
		cls.empty = cls._project("Empty", [])

	@classmethod
	def tearDownClass(cls):
		for project in (cls.alpha, cls.beta, cls.empty):
			frappe.delete_doc("Project", project, force=True, ignore_permissions=True)
		settings = frappe.get_single("Frappe Agile Settings")
		settings.set("development_team", [])
		for email in cls.original_team:
			settings.append("development_team", {"user": email})
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	@classmethod
	def _project(cls, suffix, users):
		name = f"{PREFIX} {suffix}"
		if frappe.db.exists("Project", name):
			frappe.delete_doc("Project", name, force=True, ignore_permissions=True)
		project = frappe.get_doc({"doctype": "Project", "project_name": name})
		for email in users:
			project.append("users", {"user": email})
		project.insert(ignore_permissions=True)
		return project.name

	def _ours(self, users):
		"""Only the fixture users, so whatever else the site has on its projects
		does not decide these tests."""
		return sorted(u for u in users if u.startswith(_stem))

	def test_a_project_offers_exactly_its_own_users(self):
		self.assertEqual(get_assignable_users(project=self.alpha), sorted([ON_ALPHA, ON_BOTH]))
		self.assertEqual(get_assignable_users(project=self.beta), sorted([ON_BETA, ON_BOTH]))

	def test_without_a_project_everyone_on_any_project_is_offered_once(self):
		self.assertEqual(
			self._ours(get_assignable_users()), sorted([ON_ALPHA, ON_BOTH, ON_BETA])
		)

	def test_the_development_team_has_no_say(self):
		"""On the team and on no project: not offered anywhere."""
		self.assertNotIn(ON_TEAM_ONLY, get_assignable_users())
		self.assertNotIn(ON_TEAM_ONLY, get_assignable_users(project=self.alpha))

	def test_a_project_naming_nobody_offers_nobody(self):
		"""The old selector fell back to the team here. Falling back hid the
		real gap, which is that the project has no users."""
		self.assertEqual(get_assignable_users(project=self.empty), [])

	def test_an_unknown_project_offers_nobody(self):
		self.assertEqual(get_assignable_users(project="_Test Assignee Nonexistent"), [])

	def test_the_reviewers_are_the_development_team(self):
		"""Reviewing does not go through the project."""
		self.assertEqual(get_development_team_users(), [ON_TEAM_ONLY])

	def test_a_project_user_is_not_a_reviewer_by_itself(self):
		self.assertNotIn(ON_ALPHA, get_development_team_users())
