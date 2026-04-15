"""Tests for Sprint doctype."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, add_days


class TestSprint(FrappeTestCase):
	def setUp(self):
		"""Clean up any test sprints before each test."""
		frappe.db.delete("Sprint", {"sprint_prefix": ("in", ["TEST", "ALPHA", "BETA"])})
		frappe.db.commit()
		# Frappe resets transaction_writes to 0 when a COMMIT or ROLLBACK
		# SQL query is processed by check_transaction_status(). However,
		# earlier test classes may have accumulated a large counter.
		# Explicitly reset it to guarantee Sprint tests start with a clean
		# write budget and avoid TooManyWritesError.
		frappe.db.transaction_writes = 0

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
		wi1 = frappe.get_doc({
			"doctype": "Work Item",
			"work_item_type": "User Story",
			"title": "Test WI 1",
			"sprint": sprint.name,
			"story_points": 5,
		})
		wi1.insert(ignore_permissions=True)

		wi2 = frappe.get_doc({
			"doctype": "Work Item",
			"work_item_type": "User Story",
			"title": "Test WI 2",
			"sprint": sprint.name,
			"story_points": 8,
		})
		wi2.insert(ignore_permissions=True)

		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 13.0)

	def tearDown(self):
		frappe.db.rollback()
