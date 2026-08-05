"""Roadmap board tests — the row axis is always the active SCRUM Project.

Covers the WI-001819 behaviour: "Group rows by" is gone, the board only ever
shows active SCRUM projects, and a Project Status multi-select narrows that set.
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate

from frappe_agile.frappe_agile.page.roadmap_board.roadmap_board import (
	create_missing_sprints,
	get_roadmap_data,
	move_work_item,
)
from frappe_agile.frappe_agile.doctype.sprint.sprint import (
	SPRINT_SPAN_DAYS,
	align_to_sprint_start,
)

# Every fixture project name starts with this so teardown can find them all.
TEST_PREFIX = "RMTEST"

PROJECTS = {
	# name suffix        (project_type,   is_active, status,      sprint_prefix)
	"OPEN": ("SCRUM Project", "Yes", "Open", "RMTESTOPEN"),
	"COMPLETED": ("SCRUM Project", "Yes", "Completed", "RMTESTCOMP"),
	"CANCELLED": ("SCRUM Project", "Yes", "Cancelled", "RMTESTCANC"),
	# Excluded from the board: inactive, and not a SCRUM project.
	"INACTIVE": ("SCRUM Project", "No", "Open", "RMTESTINAC"),
	"NOTSCRUM": ("Internal", "Yes", "Open", "RMTESTNSCR"),
	# Active SCRUM but no Sprint Prefix — shows as a lane, cannot be planned into.
	"NOPREFIX": ("SCRUM Project", "Yes", "Open", None),
}


class TestRoadmapBoard(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Company", {}, "name")

	def setUp(self):
		self._cleanup()
		self.projects = {key: self._make_project(key) for key in PROJECTS}
		frappe.db.commit()

	def tearDown(self):
		self._cleanup()
		frappe.db.commit()

	# ------------------------------------------------------------------
	# Fixtures
	# ------------------------------------------------------------------
	def _project_name(self, key):
		return f"{TEST_PREFIX} {key}"

	def _make_project(self, key):
		project_type, is_active, status, prefix = PROJECTS[key]
		doc = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": self._project_name(key),
				"project_type": project_type,
				"is_active": is_active,
				"status": status,
				"custom_sprint_prefix": prefix,
				"company": self.company,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_sprint(self, project_key, start_date, status="Draft"):
		start = getdate(start_date)
		doc = frappe.get_doc(
			{
				"doctype": "Sprint",
				"project": self.projects[project_key],
				"sprint_prefix": PROJECTS[project_key][3],
				"status": status,
				"start_date": start,
				"end_date": add_days(start, SPRINT_SPAN_DAYS),
				"sprint_goal": "Roadmap board test",
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_work_item(self, title, sprint, story_points=3, status="Open"):
		doc = frappe.get_doc(
			{
				"doctype": "Work Item",
				"work_item_type": "User Story",
				"title": title,
				"sprint": sprint,
				"story_points": story_points,
				"status": status,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _cleanup(self):
		projects = frappe.get_all(
			"Project", filters={"project_name": ("like", f"{TEST_PREFIX}%")}, pluck="name"
		)
		sprints = (
			frappe.get_all("Sprint", filters={"project": ("in", projects)}, pluck="name")
			if projects
			else []
		)
		sprints += frappe.get_all(
			"Sprint", filters={"sprint_prefix": ("like", f"{TEST_PREFIX}%")}, pluck="name"
		)
		sprints = list(set(sprints))

		if sprints:
			frappe.db.delete("Sprint Work Item", {"parent": ("in", sprints)})
			frappe.db.delete("Work Item", {"sprint": ("in", sprints)})
			frappe.db.delete("Sprint", {"name": ("in", sprints)})

		frappe.db.delete("Work Item", {"title": ("like", f"{TEST_PREFIX}%")})
		if projects:
			frappe.db.delete("Project", {"name": ("in", projects)})

	def _rows(self, data):
		"""Only the fixture rows, keyed by project name (the board shows real ones too)."""
		return {r["key"]: r for r in data["rows"] if r["label"].startswith(TEST_PREFIX)}

	# ------------------------------------------------------------------
	# Row axis: active SCRUM projects only
	# ------------------------------------------------------------------
	def test_rows_are_active_scrum_projects_only(self):
		data = get_roadmap_data()
		rows = self._rows(data)

		self.assertIn(self.projects["OPEN"], rows)
		self.assertIn(self.projects["COMPLETED"], rows)
		self.assertIn(self.projects["CANCELLED"], rows)
		self.assertIn(self.projects["NOPREFIX"], rows)
		# Is Active = No and a non-SCRUM project type are both excluded outright.
		self.assertNotIn(self.projects["INACTIVE"], rows)
		self.assertNotIn(self.projects["NOTSCRUM"], rows)

	def test_row_carries_prefix_and_project_status(self):
		rows = self._rows(get_roadmap_data())

		row = rows[self.projects["OPEN"]]
		self.assertEqual(row["prefix"], "RMTESTOPEN")
		self.assertEqual(row["project_status"], "Open")
		# No prefix means the lane renders but nothing can be planned into it.
		self.assertEqual(rows[self.projects["NOPREFIX"]]["prefix"], "")

	def test_project_without_sprints_still_gets_a_lane_and_axis(self):
		"""A brand-new project must be plannable, so it needs a row and columns."""
		data = get_roadmap_data(lane=self.projects["OPEN"])

		self.assertEqual([r["key"] for r in data["rows"]], [self.projects["OPEN"]])
		self.assertEqual(data["cells"], {})
		self.assertTrue(data["columns"], "expected a future axis even with no sprints")
		self.assertTrue(any(c["is_current"] for c in data["columns"]))

	# ------------------------------------------------------------------
	# Project Status multi-select
	# ------------------------------------------------------------------
	def test_project_status_filter_narrows_rows(self):
		rows = self._rows(get_roadmap_data(project_status=["Open"]))
		self.assertIn(self.projects["OPEN"], rows)
		self.assertNotIn(self.projects["COMPLETED"], rows)
		self.assertNotIn(self.projects["CANCELLED"], rows)

	def test_project_status_accepts_multiple_values_as_json(self):
		"""The client posts the multi-select as a JSON list."""
		rows = self._rows(get_roadmap_data(project_status=json.dumps(["Open", "Cancelled"])))
		self.assertIn(self.projects["OPEN"], rows)
		self.assertIn(self.projects["CANCELLED"], rows)
		self.assertNotIn(self.projects["COMPLETED"], rows)

	def test_empty_project_status_shows_every_status(self):
		for empty in (None, "", [], "[]"):
			rows = self._rows(get_roadmap_data(project_status=empty))
			self.assertIn(self.projects["COMPLETED"], rows, f"failed for {empty!r}")

	def test_unknown_status_values_are_dropped(self):
		"""A forged status must not widen the query past the three real ones."""
		rows = self._rows(get_roadmap_data(project_status=json.dumps(["Open", "Bogus"])))
		self.assertIn(self.projects["OPEN"], rows)
		self.assertNotIn(self.projects["COMPLETED"], rows)

	# ------------------------------------------------------------------
	# Cells
	# ------------------------------------------------------------------
	def test_cells_are_keyed_by_project_and_window(self):
		start = align_to_sprint_start(getdate())
		sprint = self._make_sprint("OPEN", start)
		self._make_work_item(f"{TEST_PREFIX} story", sprint, story_points=5)

		data = get_roadmap_data(lane=self.projects["OPEN"])
		cell_key = f"{self.projects['OPEN']}::{getdate(start).isoformat()}"

		self.assertIn(cell_key, data["cells"])
		cell = data["cells"][cell_key]
		self.assertEqual(cell["sprint"], sprint)
		self.assertEqual(cell["total_points"], 5)
		self.assertEqual(self._rows(data)[self.projects["OPEN"]]["sprint_count"], 1)

	def test_sprint_status_filter_still_applies(self):
		start = align_to_sprint_start(getdate())
		self._make_sprint("OPEN", start, status="Draft")

		data = get_roadmap_data(lane=self.projects["OPEN"], sprint_status="Active")
		# The lane survives (it's a project) but its Draft sprint is filtered out.
		self.assertIn(self.projects["OPEN"], self._rows(data))
		self.assertEqual(data["cells"], {})

	# ------------------------------------------------------------------
	# Create missing sprints
	# ------------------------------------------------------------------
	def test_create_missing_sprints_fills_selected_projects_only(self):
		result = create_missing_sprints(
			future_count=2, lanes=json.dumps([self.projects["OPEN"]])
		)
		self.assertEqual(result["created_count"], 2)

		created = frappe.get_all(
			"Sprint",
			filters={"name": ("in", result["created"])},
			fields=["project", "sprint_prefix", "status"],
		)
		for row in created:
			self.assertEqual(row.project, self.projects["OPEN"])
			self.assertEqual(row.sprint_prefix, "RMTESTOPEN")
			self.assertEqual(row.status, "Draft")

		# Nothing was created for the projects that weren't ticked.
		self.assertFalse(
			frappe.db.exists("Sprint", {"project": self.projects["COMPLETED"]})
		)

	def test_create_missing_sprints_is_idempotent(self):
		lanes = json.dumps([self.projects["OPEN"]])
		self.assertEqual(create_missing_sprints(future_count=2, lanes=lanes)["created_count"], 2)
		self.assertEqual(create_missing_sprints(future_count=2, lanes=lanes)["created_count"], 0)

	def test_create_missing_sprints_skips_prefixless_project(self):
		result = create_missing_sprints(
			future_count=2, lanes=json.dumps([self.projects["NOPREFIX"]])
		)
		self.assertEqual(result["created_count"], 0)

	def test_missing_count_ignores_prefixless_project(self):
		data = get_roadmap_data(lane=self.projects["NOPREFIX"], future_count=4)
		self.assertEqual(data["missing_count"], 0)

		data = get_roadmap_data(lane=self.projects["OPEN"], future_count=4)
		self.assertEqual(data["missing_count"], 4)

	# ------------------------------------------------------------------
	# Drag & drop into an empty slot
	# ------------------------------------------------------------------
	def test_move_into_empty_slot_creates_sprint_on_that_project(self):
		start = align_to_sprint_start(getdate())
		source = self._make_sprint("OPEN", start)
		item = self._make_work_item(f"{TEST_PREFIX} draggable", source)

		window_start = add_days(start, 7)
		result = move_work_item(
			work_item=item,
			lane=self.projects["COMPLETED"],
			window_start=window_start,
			window_end=add_days(window_start, SPRINT_SPAN_DAYS),
		)

		self.assertTrue(result["created"])
		created = frappe.get_doc("Sprint", result["target_sprint"])
		self.assertEqual(created.project, self.projects["COMPLETED"])
		self.assertEqual(created.sprint_prefix, "RMTESTCOMP")
		self.assertEqual(getdate(created.start_date), getdate(window_start))
		self.assertEqual(frappe.db.get_value("Work Item", item, "sprint"), created.name)

	def test_move_into_empty_slot_of_prefixless_project_is_refused(self):
		start = align_to_sprint_start(getdate())
		source = self._make_sprint("OPEN", start)
		item = self._make_work_item(f"{TEST_PREFIX} stuck", source)

		with self.assertRaises(frappe.ValidationError):
			move_work_item(
				work_item=item,
				lane=self.projects["NOPREFIX"],
				window_start=add_days(start, 7),
			)

	def test_move_into_empty_slot_of_non_scrum_project_is_refused(self):
		start = align_to_sprint_start(getdate())
		source = self._make_sprint("OPEN", start)
		item = self._make_work_item(f"{TEST_PREFIX} offboard", source)

		with self.assertRaises(frappe.ValidationError):
			move_work_item(
				work_item=item,
				lane=self.projects["NOTSCRUM"],
				window_start=add_days(start, 7),
			)
