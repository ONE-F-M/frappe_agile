# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

"""Work Item tests.

Covers the `orchestrator` flag (WI-002112): the flag that tells the Software
Development process to take the orchestrator path instead of assigning the item
to a person.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

TEST_PREFIX = "WIORCH"
TEST_PROJECT = "Test Work Item Orchestrator Project"
TITLE_PREFIX = "Test Work Item Orchestrator"


class TestWorkItem(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._cleanup()
		cls.project = cls._test_project()
		cls.sprint = cls._test_sprint()

	@classmethod
	def tearDownClass(cls):
		cls._cleanup()
		super().tearDownClass()

	# ------------------------------------------------------------------
	# Fixtures
	# ------------------------------------------------------------------

	@classmethod
	def _cleanup(cls):
		"""Work Items first — Sprint Work Item rows hang off them."""
		frappe.db.delete("Work Item", {"title": ("like", f"{TITLE_PREFIX}%")})
		sprints = frappe.get_all("Sprint", {"sprint_prefix": TEST_PREFIX}, pluck="name")
		if sprints:
			frappe.db.delete("Sprint Work Item", {"parent": ("in", sprints)})
			frappe.db.delete("Sprint", {"sprint_prefix": TEST_PREFIX})
		frappe.db.commit()

	@classmethod
	def _test_project(cls):
		"""`sprint_prefix` on Sprint is a fetch_from of the Project's prefix, so a
		Sprint can only get TEST_PREFIX by hanging off a Project that carries it."""
		existing = frappe.db.get_value("Project", {"project_name": TEST_PROJECT}, "name")
		if existing:
			frappe.db.set_value("Project", existing, "custom_sprint_prefix", TEST_PREFIX)
			return existing

		project = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": TEST_PROJECT,
				"custom_sprint_prefix": TEST_PREFIX,
			}
		)
		project.insert(ignore_permissions=True)
		frappe.db.commit()
		return project.name

	@classmethod
	def _test_sprint(cls):
		"""Every non-Epic Work Item needs an Active or Draft Sprint to save at all."""
		start = today()
		sprint = frappe.get_doc(
			{
				"doctype": "Sprint",
				"sprint_prefix": TEST_PREFIX,
				"project": cls.project,
				"status": "Draft",
				"start_date": start,
				"end_date": add_days(start, 14),
				"sprint_goal": "Test Sprint Goal",
			}
		)
		sprint.insert(ignore_permissions=True)
		frappe.db.commit()
		return sprint.name

	def _work_item(self, title, **kwargs):
		values = {
			"doctype": "Work Item",
			"work_item_type": "User Story",
			"title": f"{TITLE_PREFIX} {title}",
			"sprint": self.sprint,
			"status": "Open",
			"workflow_state": "Open",
			# Explicit, and not incidental: leaving this unset makes a second save
			# fail inside _sync_with_sprint on a pre-existing NULL story_points bug
			# that has nothing to do with the orchestrator flag.
			"story_points": 3,
		}
		values.update(kwargs)
		doc = frappe.get_doc(values)
		doc.insert(ignore_permissions=True)
		return doc

	# ------------------------------------------------------------------
	# The field exists and is a real Check
	# ------------------------------------------------------------------

	def test_orchestrator_field_exists_as_a_check(self):
		field = frappe.get_meta("Work Item").get_field("orchestrator")
		self.assertIsNotNone(field, "Work Item has no `orchestrator` field")
		self.assertEqual(field.fieldtype, "Check")

	def test_orchestrator_defaults_to_off(self):
		"""No existing item becomes an orchestrator item just by being saved."""
		item = self._work_item("defaults off")
		self.assertFalse(item.orchestrator)

	def test_orchestrator_persists_when_set(self):
		item = self._work_item("flag persists", orchestrator=1)
		item.reload()
		self.assertTrue(item.orchestrator)

	# ------------------------------------------------------------------
	# The orchestrator is the assignee
	# ------------------------------------------------------------------

	def test_setting_orchestrator_clears_a_human_assignee(self):
		"""Two owners on one record leaves nobody able to say who acts."""
		item = self._work_item(
			"clears assignee", orchestrator=1, assignee_user="Administrator"
		)
		item.reload()
		self.assertTrue(item.orchestrator)
		self.assertFalse(item.assignee_user)

	def test_human_assignee_survives_when_orchestrator_is_off(self):
		"""The clearing is scoped to the flag — normal assignment is untouched."""
		item = self._work_item("keeps assignee", assignee_user="Administrator")
		item.reload()
		self.assertEqual(item.assignee_user, "Administrator")

	def test_clearing_the_flag_lets_a_human_be_assigned_again(self):
		item = self._work_item("handed back", orchestrator=1)
		item.orchestrator = 0
		item.assignee_user = "Administrator"
		item.save(ignore_permissions=True)
		item.reload()
		self.assertEqual(item.assignee_user, "Administrator")

	# ------------------------------------------------------------------
	# An Epic is a container, not something to implement
	# ------------------------------------------------------------------

	def test_an_epic_cannot_be_flagged_orchestrator(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Work Item",
					"work_item_type": "Epic",
					"title": f"{TITLE_PREFIX} epic rejected",
					"orchestrator": 1,
				}
			).insert(ignore_permissions=True)

	def test_an_epic_without_the_flag_still_saves(self):
		"""The guard must not catch the ordinary Epic path."""
		epic = frappe.get_doc(
			{
				"doctype": "Work Item",
				"work_item_type": "Epic",
				"title": f"{TITLE_PREFIX} epic allowed",
			}
		)
		epic.insert(ignore_permissions=True)
		self.assertFalse(epic.orchestrator)

	def test_retyping_a_flagged_item_to_epic_is_rejected(self):
		"""The guard holds on update, not just on insert."""
		item = self._work_item("retyped to epic", orchestrator=1)
		item.work_item_type = "Epic"
		item.epic = None
		item.sprint = None
		with self.assertRaises(frappe.ValidationError):
			item.save(ignore_permissions=True)
