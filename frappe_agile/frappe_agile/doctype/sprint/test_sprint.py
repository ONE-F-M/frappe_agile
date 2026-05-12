"""Tests for Sprint doctype."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, add_days


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
		frappe.db.delete("Work Item", {"title": ("like", "WI %pts")})

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


	def test_move_to_new_sprint(self):
		"""Incomplete items should move to a new sprint with correct dates."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		# 1. Setup source sprint and items
		sprint = self._make_sprint(prefix="TEST", status="Active")

		wi1 = self._make_work_item("Test WI 1", sprint.name, story_points=5)
		wi2 = self._make_work_item("Test WI 2", sprint.name, story_points=8)

		# Add items to sprint child table (simulating UI behavior)
		sprint.append("work_items", {
			"work_item": wi1.name,
			"work_item_type": wi1.work_item_type,
			"title": wi1.title,
			"status": wi1.status,
			"story_points": wi1.story_points
		})
		sprint.append("work_items", {
			"work_item": wi2.name,
			"work_item_type": wi2.work_item_type,
			"title": wi2.title,
			"status": wi2.status,
			"story_points": wi2.story_points
		})
		sprint.save()

		old_end_date = sprint.end_date

		# 2. Move items to new sprint
		new_sprint_name = handle_incomplete_items(sprint.name, action="Move to New Sprint")

		# 3. Verify new sprint
		self.assertTrue(new_sprint_name)
		new_sprint = frappe.get_doc("Sprint", new_sprint_name)

		from frappe.utils import getdate
		self.assertEqual(getdate(new_sprint.start_date), getdate(add_days(old_end_date, 1)))
		self.assertEqual(getdate(new_sprint.end_date), getdate(add_days(new_sprint.start_date, 7)))

		# Verify items moved
		self.assertEqual(len(new_sprint.work_items), 2)
		moved_items = [d.work_item for d in new_sprint.work_items]
		self.assertIn(wi1.name, moved_items)
		self.assertIn(wi2.name, moved_items)

		# Verify Work Item records updated
		self.assertEqual(frappe.db.get_value("Work Item", wi1.name, "sprint"), new_sprint_name)

		# Verify old sprint velocity preserved
		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 13.0)

	def tearDown(self):
		# Explicit cleanup for data committed by handle_incomplete_items
		self._cleanup_test_data()
		frappe.db.rollback()

