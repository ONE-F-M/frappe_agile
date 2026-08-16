"""Tests for Sprint doctype."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, add_days, flt, getdate


# Prefixes used by tests — any Sprint / Work Item using these is test data.
TEST_PREFIXES = ["TEST", "ALPHA", "BETA"]

# Each test prefix gets its own Project, since Sprint.sprint_prefix is fetched
# read-only from Project.custom_sprint_prefix.
TEST_PROJECT_PREFIX = "_Test Agile Sprint "


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

	def _test_project(self, prefix):
		"""Get-or-create the Project that test Sprints of *prefix* hang off.

		`project` is mandatory on Sprint, and `sprint_prefix` is a read-only
		`fetch_from` of `project.custom_sprint_prefix` — so the prefix a Sprint
		ends up with is decided by its Project, not by what the caller passes.
		That means one Project per test prefix. Created once and reused; these
		are deliberately not torn down, since a rollback would pull them out
		from under sprints committed by handle_incomplete_items().
		"""
		project_name = f"{TEST_PROJECT_PREFIX}{prefix}"
		existing = frappe.db.get_value("Project", {"project_name": project_name}, "name")
		if existing:
			frappe.db.set_value("Project", existing, "custom_sprint_prefix", prefix)
			return existing

		project = frappe.get_doc({
			"doctype": "Project",
			"project_name": project_name,
			"custom_sprint_prefix": prefix,
		})
		project.insert(ignore_permissions=True)
		frappe.db.commit()
		return project.name

	def _make_sprint(
		self,
		prefix="TEST",
		status="Draft",
		project=None,
		sprint_goal="Test Sprint Goal",
		start_date=None,
		end_date=None,
	):
		start = start_date or today()
		sprint = frappe.get_doc({
			"doctype": "Sprint",
			"sprint_prefix": prefix,
			"status": status,
			"project": project or self._test_project(prefix),
			"start_date": start,
			"end_date": end_date or add_days(start, 14),
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

	def test_velocity_updates_on_work_item_moved_to_other_sprint(self):
		"""Moving a Work Item out of a Sprint should reduce its expected velocity.

		Work Items can no longer be left without a sprint (no backlog), so the
		reduction is driven by reassigning the item to a different sprint.
		"""
		sprint = self._make_sprint(prefix="TEST")
		other_sprint = self._make_sprint(prefix="BETA")

		wi1 = self._make_work_item("WI Remove Test 1", sprint.name, story_points=5)
		self._make_work_item("WI Remove Test 2", sprint.name, story_points=8)

		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 13.0)

		# Move wi1 to another sprint
		wi1.sprint = other_sprint.name
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

		# Move incomplete items to the next sprint
		new_sprint_name = handle_incomplete_items(sprint.name)
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

		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items
		handle_incomplete_items(sprint=sprint.name)

		# Now complete the sprint
		sprint.reload()
		sprint.status = "Completed"
		sprint.save(ignore_permissions=True)

		sprint.reload()
		self.assertEqual(
			sprint.expected_velocity, 16.0,
			"Expected Velocity was reset to 0 on sprint close!"
		)

	def test_velocity_frozen_on_carry_forward(self):
		"""Completing a sprint that carries items forward should freeze velocity
		at the pre-completion value, not reset it to 0."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")

		self._make_work_item("WI Carry Test 1", sprint.name, story_points=5)
		self._make_work_item("WI Carry Test 2", sprint.name, story_points=3)

		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 8.0)

		# Carry incomplete items forward to the next sprint
		result = handle_incomplete_items(sprint.name)
		self.assertTrue(result)

		# Now simulate the completion save
		sprint.reload()
		sprint.status = "Completed"
		sprint.save(ignore_permissions=True)

		# Velocity should be frozen at 8.0, NOT reset to 0
		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 8.0)

		# Child rows must remain on the completing sprint as a historical record
		child_rows = frappe.get_all(
			"Sprint Work Item",
			filters={"parent": sprint.name},
			fields=["name"]
		)
		self.assertEqual(
			len(child_rows), 2,
			"Sprint Work Item rows must be preserved as a historical record after carry forward"
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
		handle_incomplete_items(sprint.name)

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
		result = handle_incomplete_items(sprint.name)
		self.assertIsNone(result)

		stories_cf = frappe.db.get_value("Sprint", sprint.name, "stories_carried_forward")
		points_cf = frappe.db.get_value("Sprint", sprint.name, "points_carried_forward")
		self.assertEqual(flt(stories_cf), 0.0)
		self.assertEqual(flt(points_cf), 0.0)

	def test_child_table_preserved_on_carry_forward(self):
		"""Sprint Work Item rows must remain on the completing sprint (as a frozen
		historical record) when incomplete items are carried forward."""
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

		target_sprint = handle_incomplete_items(sprint.name)

		# Work Items must be moved to the next sprint (never left without one)
		self.assertEqual(frappe.db.get_value("Work Item", wi1.name, "sprint"), target_sprint)
		self.assertEqual(frappe.db.get_value("Work Item", wi2.name, "sprint"), target_sprint)

		# Sprint Work Item rows must NOT be deleted — they are the historical record
		post_rows = frappe.get_all(
			"Sprint Work Item",
			filters={"parent": sprint.name},
			fields=["work_item"]
		)
		self.assertEqual(
			len(post_rows), 2,
			"Child rows must survive carry forward as a frozen historical record"
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

		new_sprint_name = handle_incomplete_items(sprint.name)
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

		new_sprint_name = handle_incomplete_items(sprint.name)
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
		"""Completing a sprint must keep the frozen velocity even when the form
		payload carries expected_velocity = 0 after items were moved out."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")
		self._make_work_item("WI Vel Bug 1", sprint.name, story_points=5)
		self._make_work_item("WI Vel Bug 2", sprint.name, story_points=7)

		sprint.reload()
		self.assertEqual(sprint.expected_velocity, 12.0)

		handle_incomplete_items(sprint.name)

		# Reload to get the correct DB snapshot (12), then overwrite the in-memory
		# value with 0 as the client form payload would.
		sprint.reload()
		sprint.expected_velocity = 0
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
		"""points_accepted must NOT change after a sprint is marked Completed.

		Work Items can no longer be added to a Completed sprint, so the freeze is
		verified by attempting a recalculation directly — it must be a no-op for
		a Completed sprint.
		"""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import _recalculate_accepted_points

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

		# A recalculation attempt after completion must be ignored (frozen).
		# force=False mirrors the normal recalc path triggered by Work Item saves.
		_recalculate_accepted_points(sprint.name)

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

		# Complete sprint: carry wi2 forward to the next sprint
		handle_incomplete_items(sprint.name)
		sprint.reload()
		sprint.status = "Completed"
		sprint.save(ignore_permissions=True)

		# At completion, only wi1 was Done → accepted = 5.0
		sprint.reload()
		self.assertEqual(flt(sprint.points_accepted, 1), 5.0)

	# --- Reusing vs creating the next sprint on close ----------------------

	def _sprint_count(self, prefix="TEST"):
		return frappe.db.count("Sprint", {"sprint_prefix": prefix})

	def test_creates_next_sprint_when_none_exists(self):
		"""With no sprint scheduled after this one, closing creates exactly one."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")
		self._make_work_item("Test WI Create 1", sprint.name, story_points=3)
		self.assertEqual(self._sprint_count(), 1)

		target = handle_incomplete_items(sprint.name)

		self.assertIsNotNone(target)
		self.assertNotEqual(target, sprint.name)
		self.assertEqual(self._sprint_count(), 2, "Exactly one new sprint should be created")
		self.assertEqual(frappe.db.get_value("Sprint", target, "status"), "Draft")

	def test_reuses_existing_next_sprint(self):
		"""A sprint already scheduled for the following window is reused, not duplicated."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")
		next_sprint = self._make_sprint(
			prefix="TEST",
			status="Draft",
			start_date=add_days(sprint.end_date, 1),
			end_date=add_days(sprint.end_date, 7),
			sprint_goal="Already Planned",
		)
		wi = self._make_work_item("Test WI Reuse 1", sprint.name, story_points=5)
		self.assertEqual(self._sprint_count(), 2)

		target = handle_incomplete_items(sprint.name)

		self.assertEqual(target, next_sprint.name, "The existing next sprint should be reused")
		self.assertEqual(self._sprint_count(), 2, "No extra sprint should be created")
		self.assertEqual(frappe.db.get_value("Work Item", wi.name, "sprint"), next_sprint.name)
		# The planned sprint keeps its own goal — reuse must not overwrite it
		self.assertEqual(frappe.db.get_value("Sprint", next_sprint.name, "sprint_goal"), "Already Planned")

	def test_reuses_existing_next_sprint_off_cadence(self):
		"""Reuse must not depend on the next sprint matching the computed Wed→Tue window.

		Regression: matching on the exact computed start date missed a sprint the
		team had planned on any other day and silently created a duplicate.
		"""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import (
			_build_new_sprint_dates,
			handle_incomplete_items,
		)

		sprint = self._make_sprint(prefix="TEST", status="Active")

		# Deliberately start the planned sprint on a day that is NOT the window
		# the cadence helper would compute.
		computed_start, _computed_end = _build_new_sprint_dates(sprint)
		off_cadence_start = add_days(sprint.end_date, 1)
		if getdate(off_cadence_start) == getdate(computed_start):
			off_cadence_start = add_days(off_cadence_start, 1)
		self.assertNotEqual(getdate(off_cadence_start), getdate(computed_start))

		next_sprint = self._make_sprint(
			prefix="TEST",
			status="Draft",
			start_date=off_cadence_start,
			end_date=add_days(off_cadence_start, 6),
		)
		self._make_work_item("Test WI Offcadence 1", sprint.name, story_points=2)

		target = handle_incomplete_items(sprint.name)

		self.assertEqual(target, next_sprint.name)
		self.assertEqual(self._sprint_count(), 2, "Off-cadence next sprint must not be duplicated")

	def test_ignores_completed_sprint_when_finding_next(self):
		"""A Completed sprint after this one is not a valid carry-forward target."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")
		done_next = self._make_sprint(
			prefix="TEST",
			status="Completed",
			start_date=add_days(sprint.end_date, 1),
			end_date=add_days(sprint.end_date, 7),
		)
		self._make_work_item("Test WI Skip Completed 1", sprint.name, story_points=1)

		target = handle_incomplete_items(sprint.name)

		self.assertNotEqual(target, done_next.name, "Items must never move into a Completed sprint")
		self.assertEqual(self._sprint_count(), 3, "A fresh sprint should be created instead")

	def test_picks_earliest_of_several_future_sprints(self):
		"""When several sprints are planned ahead, the soonest one receives the items."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")
		# Insert the later sprint first, so creation order cannot be what decides it.
		self._make_sprint(
			prefix="TEST",
			status="Draft",
			start_date=add_days(sprint.end_date, 15),
			end_date=add_days(sprint.end_date, 21),
		)
		soonest = self._make_sprint(
			prefix="TEST",
			status="Draft",
			start_date=add_days(sprint.end_date, 1),
			end_date=add_days(sprint.end_date, 7),
		)
		self._make_work_item("Test WI Earliest 1", sprint.name, story_points=3)

		target = handle_incomplete_items(sprint.name)

		self.assertEqual(target, soonest.name)
		self.assertEqual(self._sprint_count(), 3, "No extra sprint should be created")

	def test_reuse_does_not_cross_prefixes(self):
		"""A sprint belonging to another prefix is never reused as the target."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")
		other = self._make_sprint(
			prefix="ALPHA",
			status="Draft",
			start_date=add_days(sprint.end_date, 1),
			end_date=add_days(sprint.end_date, 7),
		)
		self._make_work_item("Test WI Other Prefix 1", sprint.name, story_points=2)

		target = handle_incomplete_items(sprint.name)

		self.assertNotEqual(target, other.name)
		self.assertEqual(frappe.db.get_value("Sprint", target, "sprint_prefix"), "TEST")

	def test_reused_sprint_flags_preplanned_row_as_brought_forward(self):
		"""An item already listed on the reused sprint still counts as brought forward."""
		from frappe_agile.frappe_agile.doctype.sprint.sprint import handle_incomplete_items

		sprint = self._make_sprint(prefix="TEST", status="Active")
		next_sprint = self._make_sprint(
			prefix="TEST",
			status="Draft",
			start_date=add_days(sprint.end_date, 1),
			end_date=add_days(sprint.end_date, 7),
		)
		wi = self._make_work_item("Test WI Preplanned 1", sprint.name, story_points=4)

		# Pre-plan the same work item onto the next sprint's child table.
		frappe.get_doc({
			"doctype": "Sprint Work Item",
			"parent": next_sprint.name,
			"parentfield": "work_items",
			"parenttype": "Sprint",
			"work_item": wi.name,
			"work_item_type": wi.work_item_type,
			"title": wi.title,
			"status": wi.status,
			"story_points": wi.story_points,
			"is_brought_forward": 0,
		}).insert(ignore_permissions=True)

		target = handle_incomplete_items(sprint.name)
		self.assertEqual(target, next_sprint.name)

		rows = frappe.get_all(
			"Sprint Work Item",
			filters={"parent": next_sprint.name, "work_item": wi.name},
			fields=["is_brought_forward"],
		)
		self.assertEqual(len(rows), 1, "The pre-planned row must not be duplicated")
		self.assertEqual(rows[0].is_brought_forward, 1)

		next_sprint.reload()
		self.assertEqual(next_sprint.stories_brought_forward, 1)
		self.assertEqual(flt(next_sprint.points_brought_forward, 1), 4.0)

	def tearDown(self):
		# Explicit cleanup for data committed by handle_incomplete_items
		self._cleanup_test_data()
		frappe.db.rollback()
