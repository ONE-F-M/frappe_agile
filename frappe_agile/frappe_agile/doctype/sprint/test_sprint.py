"""Tests for Sprint doctype."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, add_days, flt

from frappe_agile.tests.fixtures import (
	TEST_PREFIXES,
	delete_test_projects,
	ensure_test_project,
)


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

		# Delete test sprints, then the Projects that owned their prefixes.
		frappe.db.delete("Sprint", {"sprint_prefix": ("in", TEST_PREFIXES)})
		delete_test_projects()

	def _make_sprint(self, prefix="TEST", status="Draft", project=None, sprint_goal="Test Sprint Goal"):
		# Sprint.project is mandatory and sprint_prefix is fetched from it, so the
		# prefix is expressed by giving the sprint a Project that owns it.
		sprint = frappe.get_doc({
			"doctype": "Sprint",
			"status": status,
			"project": project or ensure_test_project(prefix),
			"start_date": today(),
			"end_date": add_days(today(), 14),
			"sprint_goal": sprint_goal,
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

		# Bug fix: child table rows must REMAIN on the completing sprint
		# as a frozen historical record (not be deleted).
		child_rows = frappe.get_all(
			"Sprint Work Item",
			filters={"parent": sprint.name},
			fields=["name"]
		)
		self.assertEqual(
			len(child_rows), 2,
			"Sprint Work Item rows must be preserved as a historical record after Move to Backlog"
		)

	def test_stories_brought_forward_on_sprint_change(self):
		"""When a Work Item is moved from Sprint A to Sprint B, Sprint B should
		show is_brought_forward=1 on its child row and aggregate counts updated."""
		from frappe.utils import cint

		sprint_a = self._make_sprint(prefix="ALPHA", status="Active")
		sprint_b = self._make_sprint(prefix="BETA", status="Active")

		# Create WI in sprint A
		wi = self._make_work_item("Test BF Move", sprint_a.name, story_points=5)

		# Move WI to sprint B (triggers is_brought_forward logic)
		wi.sprint = sprint_b.name
		wi.save(ignore_permissions=True)

		# Sprint B child row should have is_brought_forward = 1
		swi_rows = frappe.get_all(
			"Sprint Work Item",
			filters={"parent": sprint_b.name, "work_item": wi.name},
			fields=["is_brought_forward"]
		)
		self.assertEqual(len(swi_rows), 1)
		self.assertEqual(cint(swi_rows[0].is_brought_forward), 1)

		# Sprint B brought-forward aggregates should reflect the moved item
		sprint_b.reload()
		self.assertEqual(sprint_b.stories_brought_forward, 1)
		self.assertEqual(flt(sprint_b.points_brought_forward, 1), 5.0)

	def test_stories_and_points_carried_forward_on_sprint_close(self):
		"""stories_carried_forward and points_carried_forward should be set
		when a sprint completes with incomplete items."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")

		self._make_work_item("Test CF 1", sprint.name, story_points=3)
		self._make_work_item("Test CF 2", sprint.name, story_points=5)

		# Both items are Open (not Done) — all will be carried forward
		handle_incomplete_items(sprint.name, "Move to Backlog")

		stories_cf = frappe.db.get_value("Sprint", sprint.name, "stories_carried_forward")
		points_cf = frappe.db.get_value("Sprint", sprint.name, "points_carried_forward")
		self.assertEqual(stories_cf, 2)
		self.assertEqual(flt(points_cf, 1), 8.0)

	def test_carried_forward_zero_when_all_items_done(self):
		"""stories_carried_forward and points_carried_forward should remain 0
		when all Work Items are Done (no spill-over)."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")

		wi = self._make_work_item("Test No CF", sprint.name, story_points=5)
		wi.status = "Done"
		wi.workflow_state = "Done"
		wi.save(ignore_permissions=True)

		# All items Done — handle_incomplete_items finds nothing to carry forward
		result = handle_incomplete_items(sprint.name, "Move to Backlog")
		self.assertIsNone(result)

		stories_cf = frappe.db.get_value("Sprint", sprint.name, "stories_carried_forward")
		points_cf = frappe.db.get_value("Sprint", sprint.name, "points_carried_forward")
		self.assertEqual(flt(stories_cf), 0.0)
		self.assertEqual(flt(points_cf), 0.0)

	def test_child_table_preserved_on_move_to_backlog(self):
		"""Sprint Work Item rows must remain on the completing sprint (as a frozen
		historical record) when incomplete items are moved to the Backlog."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")
		wi1 = self._make_work_item("WI Child Row 1", sprint.name, story_points=3)
		wi2 = self._make_work_item("WI Child Row 2", sprint.name, story_points=5)

		# Confirm both are in the child table before closing
		pre_rows = frappe.get_all(
			"Sprint Work Item",
			filters={"parent": sprint.name},
			fields=["work_item"]
		)
		self.assertEqual(len(pre_rows), 2)

		handle_incomplete_items(sprint.name, "Move to Backlog")

		# Work Items must be moved to backlog (sprint field cleared)
		self.assertEqual(frappe.db.get_value("Work Item", wi1.name, "sprint"), "")
		self.assertEqual(frappe.db.get_value("Work Item", wi2.name, "sprint"), "")

		# Sprint Work Item rows must NOT be deleted — they are the historical record
		post_rows = frappe.get_all(
			"Sprint Work Item",
			filters={"parent": sprint.name},
			fields=["work_item"]
		)
		self.assertEqual(
			len(post_rows), 2,
			"Child rows must survive Move to Backlog as a frozen historical record"
		)
		present = {r.work_item for r in post_rows}
		self.assertIn(wi1.name, present)
		self.assertIn(wi2.name, present)

	def test_child_table_preserved_on_move_to_new_sprint(self):
		"""When incomplete items are moved to a new sprint:
		  - the completing sprint's child table rows stay (historical record)
		  - the new sprint's child table gains the rows too."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")
		wi1 = self._make_work_item("WI Move Row 1", sprint.name, story_points=2)
		wi2 = self._make_work_item("WI Move Row 2", sprint.name, story_points=4)

		new_sprint_name = handle_incomplete_items(sprint.name, "Move to New Sprint")
		self.assertTrue(new_sprint_name)

		# Completing sprint: rows preserved
		old_rows = frappe.get_all(
			"Sprint Work Item",
			filters={"parent": sprint.name},
			fields=["work_item"]
		)
		self.assertEqual(len(old_rows), 2, "Completing sprint rows must be preserved")

		# New sprint: rows added
		new_rows = frappe.get_all(
			"Sprint Work Item",
			filters={"parent": new_sprint_name},
			fields=["work_item"]
		)
		self.assertEqual(len(new_rows), 2, "New sprint must have the moved rows")
		new_wis = {r.work_item for r in new_rows}
		self.assertIn(wi1.name, new_wis)
		self.assertIn(wi2.name, new_wis)

	def test_handle_incomplete_items_sets_brought_forward_on_new_sprint(self):
		"""When handle_incomplete_items moves items to a new sprint, the new
		sprint's Sprint Work Item rows should have is_brought_forward=1 and
		the aggregate counts should be non-zero."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items
		from frappe.utils import cint, flt

		sprint = self._make_sprint(prefix="TEST", status="Active")
		self._make_work_item("Test BF Close 1", sprint.name, story_points=3)
		self._make_work_item("Test BF Close 2", sprint.name, story_points=5)

		new_sprint_name = handle_incomplete_items(sprint.name, "Move to New Sprint")
		self.assertTrue(new_sprint_name)

		# All Sprint Work Item rows on the new sprint should be is_brought_forward=1
		swi_rows = frappe.get_all(
			"Sprint Work Item",
			filters={"parent": new_sprint_name},
			fields=["is_brought_forward", "story_points"]
		)
		self.assertEqual(len(swi_rows), 2)
		for row in swi_rows:
			self.assertEqual(cint(row.is_brought_forward), 1, "is_brought_forward not set on moved row")

		# New sprint should reflect 2 stories and 8 points brought forward
		stories_bf = frappe.db.get_value("Sprint", new_sprint_name, "stories_brought_forward")
		points_bf = frappe.db.get_value("Sprint", new_sprint_name, "points_brought_forward")
		self.assertEqual(cint(stories_bf), 2)
		self.assertEqual(flt(points_bf, 1), 8.0)

	def test_velocity_not_zeroed_by_form_payload_on_completion(self):
		"""The core velocity bug: when frm.save() is called after
		handle_incomplete_items, the form payload carries expected_velocity = 0
		(all items were moved out).  on_update must restore it from doc_before
		so the completed sprint keeps the correct frozen value."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")
		self._make_work_item("WI Vel Bug 1", sprint.name, story_points=5)
		self._make_work_item("WI Vel Bug 2", sprint.name, story_points=7)

		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 12.0)

		# Step 1: simulate handle_incomplete_items (moves items, restores velocity in DB)
		handle_incomplete_items(sprint.name, "Move to Backlog")

		# Step 2: simulate frm.save() — Frappe would write the form payload
		# which carries expected_velocity = 0.  Force this by corrupting the
		# field directly in the DB before saving, then let on_update fix it.
		frappe.db.set_value("Sprint", sprint.name, "expected_velocity", 0, update_modified=False)

		# Step 3: complete the sprint (this triggers on_update)
		sprint.reload()
		sprint.status = "Completed"
		sprint.save(ignore_permissions=True)

		# Velocity must be restored to pre-completion value, NOT left as 0
		sprint.reload()
		self.assertEqual(
			sprint.expected_velocity, 12.0,
			"on_update must restore velocity from doc_before when completing — not leave it at 0"
		)

	def test_points_accepted_updates_when_work_item_done(self):
		"""points_accepted should increase when a Work Item status becomes Done."""
		sprint = self._make_sprint(prefix="TEST", status="Active")

		wi = self._make_work_item("Test WI Accepted", sprint.name, story_points=5)

		sprint.reload()
		# Initially no Work Items are Done
		self.assertEqual(flt(sprint.points_accepted, 1), 0.0)

		# Mark the Work Item as Done
		wi.status = "Done"
		wi.workflow_state = "Done"
		wi.save(ignore_permissions=True)

		sprint.reload()
		self.assertEqual(flt(sprint.points_accepted, 1), 5.0)

	def test_points_accepted_frozen_on_sprint_completion(self):
		"""points_accepted must NOT change after a sprint is marked Completed."""
		sprint = self._make_sprint(prefix="TEST", status="Active")

		wi = self._make_work_item("Test WI Freeze", sprint.name, story_points=8)

		# Mark WI as Done so accepted points are 8
		wi.status = "Done"
		wi.workflow_state = "Done"
		wi.save(ignore_permissions=True)

		sprint.reload()
		self.assertEqual(flt(sprint.points_accepted, 1), 8.0)

		# Complete the sprint
		sprint.status = "Completed"
		sprint.save(ignore_permissions=True)

		# Simulate a subsequent WI change that would normally trigger recalc
		wi2 = self._make_work_item("Test WI Post-Complete", sprint.name, story_points=3)
		wi2.status = "Done"
		wi2.workflow_state = "Done"
		wi2.save(ignore_permissions=True)

		# points_accepted must remain frozen at 8.0
		sprint.reload()
		self.assertEqual(
			flt(sprint.points_accepted, 1),
			8.0,
			"points_accepted changed after sprint was Completed"
		)

	def test_points_accepted_captured_on_completion_transition(self):
		"""points_accepted should be captured correctly at the moment of completion."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")

		wi1 = self._make_work_item("Test WI Comp 1", sprint.name, story_points=5)
		wi2 = self._make_work_item("Test WI Comp 2", sprint.name, story_points=3)

		# Mark wi1 Done, leave wi2 Open
		wi1.status = "Done"
		wi1.workflow_state = "Done"
		wi1.save(ignore_permissions=True)

		sprint.reload()
		self.assertEqual(flt(sprint.points_accepted, 1), 5.0)

		# Complete sprint: move wi2 to backlog
		handle_incomplete_items(sprint.name, "Move to Backlog")
		sprint.reload()
		sprint.status = "Completed"
		sprint.save(ignore_permissions=True)

		# At completion, only wi1 was Done → accepted = 5.0
		sprint.reload()
		self.assertEqual(flt(sprint.points_accepted, 1), 5.0)

	def tearDown(self):
		# Explicit cleanup for data committed by handle_incomplete_items
		self._cleanup_test_data()
		frappe.db.rollback()
