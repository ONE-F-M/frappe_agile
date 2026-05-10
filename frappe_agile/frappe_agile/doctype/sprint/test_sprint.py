"""Tests for Sprint doctype."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, add_days, flt


# Prefixes used by tests — any Sprint / Work Item using these is test data.
TEST_PREFIXES = ["TEST", "ALPHA", "BETA"]


class TestSprint(FrappeTestCase):
	def setUp(self):
		"""Clean up any leaked test data from prior runs.

		handle_incomplete_items() performs an unconditional frappe.db.commit(),
		so tearDown's rollback cannot clean up data created before that call.
		We explicitly delete known test records here to avoid leakage.
		"""
		self._cleanup_test_data()
		frappe.db.commit()
		# Frappe resets transaction_writes to 0 when a COMMIT or ROLLBACK
		# SQL query is processed by check_transaction_status(). However,
		# earlier test classes may have accumulated a large counter.
		# Explicitly reset it to guarantee Sprint tests start with a clean
		# write budget and avoid TooManyWritesError.
		frappe.db.transaction_writes = 0

	def _cleanup_test_data(self):
		"""Delete Sprints, Sprint Work Items, and Work Items created by tests."""
		test_sprints = frappe.get_all(
			"Sprint",
			filters={"sprint_prefix": ("in", TEST_PREFIXES)},
			fields=["name"],
			pluck="name",
		)

		if test_sprints:
			# Delete child table rows parented to test sprints
			frappe.db.delete("Sprint Work Item", {"parent": ("in", test_sprints)})
			# Delete Work Items linked to test sprints
			frappe.db.delete("Work Item", {"sprint": ("in", test_sprints)})

		# Delete orphaned Work Items created by tests (title pattern)
		frappe.db.delete("Work Item", {"title": ("like", "Test WI%")})
		frappe.db.delete("Work Item", {"title": ("like", "WI %")})

		# Delete test sprints
		frappe.db.delete("Sprint", {"sprint_prefix": ("in", TEST_PREFIXES)})

	def _make_sprint(self, prefix="TEST", status="Draft", project=None):
		sprint = frappe.get_doc({
			"doctype": "Sprint",
			"sprint_prefix": prefix,
			"status": status,
			"project": project,
			"start_date": today(),
			"end_date": add_days(today(), 14),
		})
		sprint.insert(ignore_permissions=True)
		return sprint

	def _make_work_item(self, title, sprint_name, story_points=0):
		"""Create a Work Item compatible with the active workflow."""
		wi = frappe.get_doc({
			"doctype": "Work Item",
			"work_item_type": "User Story",
			"title": title,
			"sprint": sprint_name,
			"story_points": story_points,
			"workflow_state": "Open",
			"status": "Open",
		})
		wi.insert(ignore_permissions=True)
		return wi

	def test_autoname_format(self):
		"""Sprint name should follow format {sprint_prefix}-{##}."""
		sprint = self._make_sprint(prefix="ALPHA")
		self.assertTrue(sprint.name.startswith("ALPHA-"), f"Expected ALPHA-xx, got {sprint.name}")

	def test_active_sprint_uniqueness_same_prefix(self):
		"""Two sprints with the same prefix cannot both be Active."""
		s1 = self._make_sprint(prefix="TEST", status="Active")
		s2 = self._make_sprint(prefix="TEST", status="Draft")

		s2.status = "Active"
		self.assertRaises(frappe.ValidationError, s2.save)

	def test_multiple_active_sprints_different_prefix(self):
		"""Sprints with different prefixes can both be Active simultaneously."""
		self._make_sprint(prefix="ALPHA", status="Active")
		# Should not raise
		self._make_sprint(prefix="BETA", status="Active")

	def test_expected_velocity_calculation(self):
		"""Expected Velocity should equal the sum of Work Item story points."""
		sprint = self._make_sprint(prefix="TEST")

		# Create two work items linked to this sprint
		self._make_work_item("Test WI 1", sprint.name, story_points=5)
		self._make_work_item("Test WI 2", sprint.name, story_points=8)

		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 13.0)

	def test_velocity_updates_on_work_item_removal(self):
		"""Removing a Work Item from a Sprint should reduce expected velocity."""
		sprint = self._make_sprint(prefix="TEST")

		wi1 = self._make_work_item("WI Remove Test 1", sprint.name, story_points=5)
		self._make_work_item("WI Remove Test 2", sprint.name, story_points=8)

		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 13.0)

		# Remove wi1 from the sprint
		wi1.sprint = ""
		wi1.save(ignore_permissions=True)

		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 8.0)

	def test_velocity_on_new_sprint_after_handle_incomplete_items(self):
		"""When incomplete items are moved to a new sprint, the new sprint
		should have the correct expected velocity (not zero)."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")

		self._make_work_item("WI Move Test 1", sprint.name, story_points=3)
		self._make_work_item("WI Move Test 2", sprint.name, story_points=5)

		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 8.0)

		# Move incomplete items to a new sprint
		new_sprint_name = handle_incomplete_items(sprint.name, "Move to New Sprint")
		self.assertTrue(new_sprint_name)

		# New sprint should have the correct sum of moved story points
		new_velocity = frappe.db.get_value("Sprint", new_sprint_name, "expected_velocity")
		self.assertEqual(flt(new_velocity, 2), 8.0)

		# Now simulate the completion save (as _trigger_save does on the client)
		sprint.reload()
		sprint.status = "Completed"
		sprint.save(ignore_permissions=True)

		# Completed sprint's velocity should be frozen at the pre-completion value
		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 8.0)

		# New sprint velocity must still be correct after old sprint completion
		new_velocity_after = frappe.db.get_value("Sprint", new_sprint_name, "expected_velocity")
		self.assertEqual(flt(new_velocity_after, 2), 8.0)

	def test_velocity_preserved_on_sprint_close(self):
		"""Expected Velocity must NOT reset when a sprint is completed."""
		sprint = self._make_sprint(prefix="TEST", status="Active")

		# Create work items with story points
		for sp in [5, 8, 3]:
			self._make_work_item(f"WI {sp}pts", sprint.name, story_points=sp)

		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 16.0)

		# Simulate closing: move incomplete items out, then complete.
		# NOTE: handle_incomplete_items calls frappe.db.commit(), so data
		# created above is persisted. setUp's _cleanup_test_data handles this.
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items
		handle_incomplete_items(sprint=sprint.name, action="Move to Backlog")

		# Now complete the sprint
		sprint.reload()
		sprint.status = "Completed"
		sprint.save(ignore_permissions=True)

		sprint.reload()
		self.assertEqual(
			sprint.expected_velocity, 16.0,
			"Expected Velocity was reset to 0 on sprint close!"
		)

	def test_velocity_frozen_on_move_to_backlog(self):
		"""Completing a sprint with 'Move to Backlog' should freeze velocity
		at the pre-completion value, not reset it to 0."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")

		self._make_work_item("WI Backlog Test 1", sprint.name, story_points=5)
		self._make_work_item("WI Backlog Test 2", sprint.name, story_points=3)

		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 8.0)

		# Move items to backlog (no new sprint created)
		result = handle_incomplete_items(sprint.name, "Move to Backlog")
		self.assertIsNone(result)

		# Now simulate the completion save
		sprint.reload()
		sprint.status = "Completed"
		sprint.save(ignore_permissions=True)

		# Velocity should be frozen at 8.0, NOT reset to 0
		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 8.0)

		# Child table rows should have been cleaned up
		child_rows = frappe.get_all(
			"Sprint Work Item",
			filters={"parent": sprint.name},
			fields=["name"]
		)
		self.assertEqual(len(child_rows), 0)

	def tearDown(self):
		# Explicit cleanup for data committed by handle_incomplete_items
		self._cleanup_test_data()
		frappe.db.rollback()
