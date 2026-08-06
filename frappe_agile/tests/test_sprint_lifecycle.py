"""Sprint lifecycle tests for frappe_agile."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, today

from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items


TEST_PREFIXES = ["TEST", "ALPHA", "BETA"]

# Each test prefix gets its own Project, since Sprint.sprint_prefix is fetched
# read-only from Project.custom_sprint_prefix.
TEST_PROJECT_PREFIX = "_Test Agile Lifecycle "


class TestSprintLifecycle(FrappeTestCase):
	def setUp(self):
		self._cleanup_test_data()
		frappe.db.commit()
		frappe.db.transaction_writes = 0

	def tearDown(self):
		self._cleanup_test_data()
		frappe.db.rollback()

	def _cleanup_test_data(self):
		test_sprints = frappe.get_all(
			"Sprint",
			filters={"sprint_prefix": ("in", TEST_PREFIXES)},
			fields=["name"],
			pluck="name",
		)

		if test_sprints:
			frappe.db.delete("Sprint Work Item", {"parent": ("in", test_sprints)})
			frappe.db.delete("Work Item", {"sprint": ("in", test_sprints)})

		frappe.db.delete("Work Item", {"title": ("like", "Test Sprint Lifecycle%")})
		frappe.db.delete("Sprint", {"sprint_prefix": ("in", TEST_PREFIXES)})

	def _test_project(self, prefix):
		"""Get-or-create the Project that test Sprints of *prefix* hang off.

		`project` is mandatory on Sprint, and `sprint_prefix` is a read-only
		`fetch_from` of `project.custom_sprint_prefix`, so the prefix a Sprint
		ends up with comes from its Project — hence one Project per test prefix.
		Not torn down: a rollback would pull it out from under sprints committed
		by handle_incomplete_items().
		"""
		project_name = f"{TEST_PROJECT_PREFIX}{prefix}"
		existing = frappe.db.get_value("Project", {"project_name": project_name}, "name")
		if existing:
			frappe.db.set_value("Project", existing, "custom_sprint_prefix", prefix)
			return existing

		project = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": project_name,
				"custom_sprint_prefix": prefix,
			}
		)
		project.insert(ignore_permissions=True)
		frappe.db.commit()
		return project.name

	def _make_sprint(self, prefix="TEST", status="Draft", start_date=None, end_date=None):
		start = start_date or today()
		sprint = frappe.get_doc(
			{
				"doctype": "Sprint",
				"sprint_prefix": prefix,
				"project": self._test_project(prefix),
				"status": status,
				"start_date": start,
				"end_date": end_date or add_days(start, 14),
				"sprint_goal": "Test Sprint Goal",
			}
		)
		sprint.insert(ignore_permissions=True)
		return sprint

	def _make_work_item(self, title, sprint_name, story_points=0, status="Open"):
		wi = frappe.get_doc(
			{
				"doctype": "Work Item",
				"work_item_type": "User Story",
				"title": title,
				"sprint": sprint_name,
				"story_points": story_points,
				"workflow_state": status,
				"status": status,
			}
		)
		wi.insert(ignore_permissions=True)
		return wi

	def test_01_sprint_creation_with_start_and_end_dates(self):
		sprint = self._make_sprint(prefix="ALPHA")
		self.assertTrue(sprint.start_date)
		self.assertTrue(sprint.end_date)
		self.assertEqual(sprint.status, "Draft")

	def test_02_sprint_start_moves_draft_to_active(self):
		sprint = self._make_sprint(prefix="TEST", status="Draft")
		sprint.status = "Active"
		sprint.save(ignore_permissions=True)
		sprint.reload()
		self.assertEqual(sprint.status, "Active")

	def test_03_task_assignment_to_sprint_updates_child_table(self):
		sprint = self._make_sprint(prefix="TEST")
		wi = self._make_work_item("Test Sprint Lifecycle Task Assignment", sprint.name, 3)
		sprint.reload()
		self.assertTrue(any(row.work_item == wi.name for row in sprint.work_items))

	def test_04_story_point_tracking_updates_expected_velocity(self):
		sprint = self._make_sprint(prefix="TEST")
		self._make_work_item("Test Sprint Lifecycle Points 1", sprint.name, 5)
		self._make_work_item("Test Sprint Lifecycle Points 2", sprint.name, 8)
		sprint.reload()
		self.assertEqual(flt(sprint.expected_velocity, 2), 13.0)

	def test_05_active_sprint_uniqueness_per_prefix(self):
		self._make_sprint(prefix="TEST", status="Active")
		second = self._make_sprint(prefix="TEST", status="Draft")
		second.status = "Active"
		self.assertRaises(frappe.ValidationError, second.save)

	def test_06_completed_sprint_cannot_revert_to_active(self):
		sprint = self._make_sprint(prefix="TEST", status="Active")
		sprint.status = "Completed"
		sprint.save(ignore_permissions=True)
		sprint.reload()
		sprint.status = "Active"
		self.assertRaises(frappe.ValidationError, sprint.save)

	def test_07_sprint_completion_preserves_expected_velocity(self):
		sprint = self._make_sprint(prefix="TEST", status="Active")
		self._make_work_item("Test Sprint Lifecycle Complete 1", sprint.name, 5)
		self._make_work_item("Test Sprint Lifecycle Complete 2", sprint.name, 3)
		sprint.reload()
		self.assertEqual(flt(sprint.expected_velocity, 2), 8.0)
		handle_incomplete_items(sprint.name)
		sprint.reload()
		sprint.status = "Completed"
		sprint.save(ignore_permissions=True)
		sprint.reload()
		self.assertEqual(flt(sprint.expected_velocity, 2), 8.0)

	def test_08_incomplete_work_items_can_move_to_new_sprint(self):
		sprint = self._make_sprint(prefix="TEST", status="Active")
		self._make_work_item("Test Sprint Lifecycle Move 1", sprint.name, 2)
		self._make_work_item("Test Sprint Lifecycle Move 2", sprint.name, 6)
		new_sprint_name = handle_incomplete_items(sprint.name)
		self.assertTrue(new_sprint_name)
		new_velocity = frappe.db.get_value("Sprint", new_sprint_name, "expected_velocity")
		self.assertEqual(flt(new_velocity, 2), 8.0)

	def test_09_velocity_calculation_matches_assigned_story_points(self):
		sprint = self._make_sprint(prefix="BETA")
		for points in [5, 8, 3, 7]:
			self._make_work_item(f"Test Sprint Lifecycle Velocity {points}", sprint.name, points)
		sprint.reload()
		self.assertEqual(flt(sprint.expected_velocity, 2), 23.0)

	def test_10_burndown_data_can_be_derived_from_remaining_scope(self):
		sprint = self._make_sprint(prefix="TEST", status="Active")
		self._make_work_item("Test Sprint Lifecycle Burndown 1", sprint.name, 5, status="Open")
		self._make_work_item("Test Sprint Lifecycle Burndown 2", sprint.name, 3, status="In Progress")
		sprint.reload()
		remaining_scope = sum(row.story_points for row in sprint.work_items if row.status != "Done")
		self.assertEqual(flt(remaining_scope, 2), 8.0)

	def test_11_closing_reuses_an_already_planned_next_sprint(self):
		"""Closing a sprint moves items into the next sprint if one already exists."""
		sprint = self._make_sprint(prefix="TEST", status="Active")
		planned = self._make_sprint(
			prefix="TEST",
			status="Draft",
			start_date=add_days(sprint.end_date, 1),
			end_date=add_days(sprint.end_date, 7),
		)
		before = frappe.db.count("Sprint", {"sprint_prefix": "TEST"})

		self._make_work_item("Test Sprint Lifecycle Reuse 1", sprint.name, 2)
		self._make_work_item("Test Sprint Lifecycle Reuse 2", sprint.name, 6)

		target = handle_incomplete_items(sprint.name)

		self.assertEqual(target, planned.name)
		self.assertEqual(
			frappe.db.count("Sprint", {"sprint_prefix": "TEST"}),
			before,
			"Closing must not create a second sprint for a week already planned",
		)
		self.assertEqual(flt(frappe.db.get_value("Sprint", planned.name, "expected_velocity"), 2), 8.0)
