# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

"""Who a Work Item may be assigned to, once a project has a say.

The Development Team in Frappe Agile Settings is the standing list. A project
that names its own users narrows that list to the people on both, so work on a
Scrum project is only offered to its members. The case that needs guarding is
the project that names nobody: narrowing by an empty list would leave no
assignee at all, so the team has to stand instead.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_agile.frappe_agile.doctype.frappe_agile_settings.frappe_agile_settings import (
	get_development_team_users,
)

PREFIX = "_Test Assignee"
ON_TEAM = f"{PREFIX.lower().replace(' ', '.')}.on.team@example.com"
ALSO_ON_TEAM = f"{PREFIX.lower().replace(' ', '.')}.also.on.team@example.com"
OFF_TEAM = f"{PREFIX.lower().replace(' ', '.')}.off.team@example.com"


class TestAssigneeSelection(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for email in (ON_TEAM, ALSO_ON_TEAM, OFF_TEAM):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{
						"doctype": "User",
						"email": email,
						"first_name": email.split("@")[0],
					}
				).insert(ignore_permissions=True)

		cls.settings = frappe.get_single("Frappe Agile Settings")
		cls.original_team = [row.user for row in cls.settings.development_team]
		cls.settings.set("development_team", [])
		for email in (ON_TEAM, ALSO_ON_TEAM):
			cls.settings.append("development_team", {"user": email})
		cls.settings.save(ignore_permissions=True)

		cls.shared = cls._project("Shared", [ON_TEAM, OFF_TEAM])
		cls.strangers = cls._project("Strangers", [OFF_TEAM])
		cls.empty = cls._project("Empty", [])

	@classmethod
	def tearDownClass(cls):
		for project in (cls.shared, cls.strangers, cls.empty):
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

	def test_without_a_project_the_whole_team_is_offered(self):
		self.assertEqual(sorted(get_development_team_users()), sorted([ON_TEAM, ALSO_ON_TEAM]))

	def test_a_project_narrows_the_team_to_its_own_users(self):
		"""OFF_TEAM is on the project but not the team, ALSO_ON_TEAM the reverse —
		only the person on both may be assigned."""
		self.assertEqual(get_development_team_users(project=self.shared), [ON_TEAM])

	def test_no_overlap_offers_nobody(self):
		self.assertEqual(get_development_team_users(project=self.strangers), [])

	def test_a_project_naming_nobody_does_not_narrow(self):
		"""Narrowing by an empty Users table would leave every such project with no
		assignee at all, which is worse than not narrowing."""
		self.assertEqual(
			sorted(get_development_team_users(project=self.empty)), sorted([ON_TEAM, ALSO_ON_TEAM])
		)

	def test_an_unknown_project_does_not_narrow(self):
		self.assertEqual(
			sorted(get_development_team_users(project="_Test Assignee Nonexistent")),
			sorted([ON_TEAM, ALSO_ON_TEAM]),
		)

	def test_an_empty_team_stays_empty_whatever_the_project(self):
		"""The project can only narrow; it can never add someone the team omits."""
		settings = frappe.get_single("Frappe Agile Settings")
		settings.set("development_team", [])
		settings.save(ignore_permissions=True)
		try:
			self.assertEqual(get_development_team_users(), [])
			self.assertEqual(get_development_team_users(project=self.shared), [])
		finally:
			for email in (ON_TEAM, ALSO_ON_TEAM):
				settings.append("development_team", {"user": email})
			settings.save(ignore_permissions=True)
