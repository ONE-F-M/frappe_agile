"""Roadmap board tests — the row axis is always the active SCRUM Project.

Covers the WI-001819 behaviour: "Group rows by" is gone, the board only ever
shows active SCRUM projects, and a Project Status multi-select narrows that set;
plus WI-002020, where that same multi-select also lists the SCRUM projects so a
lane can be picked by name (the `lane` argument, which AND-s with the statuses).

That multi-select also gates the load: nothing ticked loads nothing, so tests
that mean "the whole board" tick every status via `_board`.
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate

from frappe_agile.frappe_agile.page.roadmap_board.roadmap_board import (
	ROADMAP_FLAG_FIELD,
	create_missing_sprints,
	get_roadmap_data,
	DEFAULT_BACKLOG_STATUSES,
	get_backlog_statuses,
	get_scrum_projects,
	get_unassigned_work_items,
	move_work_item,
)
from frappe_agile.frappe_agile.doctype.sprint.sprint import (
	SPRINT_SPAN_DAYS,
	align_to_sprint_start,
)

# Every fixture project name starts with this so teardown can find them all.
TEST_PREFIX = "RMTEST"

# Ticking every status is how a test asks for the whole board now that an
# untouched filter loads nothing.
ALL_STATUSES = json.dumps(["Open", "Completed", "Cancelled"])

PROJECTS = {
	# name suffix        (project_type,   is_active, status,      sprint_prefix, show_in_roadmap)
	"OPEN": ("SCRUM Project", "Yes", "Open", "RMTESTOPEN", "Yes"),
	"COMPLETED": ("SCRUM Project", "Yes", "Completed", "RMTESTCOMP", "Yes"),
	"CANCELLED": ("SCRUM Project", "Yes", "Cancelled", "RMTESTCANC", "Yes"),
	# Excluded from the board: inactive, and not a SCRUM project.
	"INACTIVE": ("SCRUM Project", "No", "Open", "RMTESTINAC", "Yes"),
	"NOTSCRUM": ("Internal", "Yes", "Open", "RMTESTNSCR", "Yes"),
	# Active SCRUM but no Sprint Prefix — shows as a lane, cannot be planned into.
	"NOPREFIX": ("SCRUM Project", "Yes", "Open", None, "Yes"),
	# Opted out / never opted in (WI-002045): active SCRUM projects that must not
	# reach the board at all. Blank is deliberately not treated as Yes.
	"HIDDEN": ("SCRUM Project", "Yes", "Open", "RMTESTHIDE", "No"),
	"UNSET": ("SCRUM Project", "Yes", "Open", "RMTESTUNST", None),
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
		project_type, is_active, status, prefix, show_in_roadmap = PROJECTS[key]
		doc = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": self._project_name(key),
				"project_type": project_type,
				"is_active": is_active,
				"status": status,
				"custom_sprint_prefix": prefix,
				ROADMAP_FLAG_FIELD: show_in_roadmap,
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

	def _board(self, **kwargs):
		"""The whole board — every status ticked, since an empty filter loads nothing."""
		kwargs.setdefault("project_status", ALL_STATUSES)
		return get_roadmap_data(**kwargs)

	def _rows(self, data):
		"""Only the fixture rows, keyed by project name (the board shows real ones too)."""
		return {r["key"]: r for r in data["rows"] if r["label"].startswith(TEST_PREFIX)}

	# ------------------------------------------------------------------
	# Row axis: active SCRUM projects only
	# ------------------------------------------------------------------
	def test_rows_are_active_scrum_projects_only(self):
		data = self._board()
		rows = self._rows(data)

		self.assertIn(self.projects["OPEN"], rows)
		self.assertIn(self.projects["COMPLETED"], rows)
		self.assertIn(self.projects["CANCELLED"], rows)
		self.assertIn(self.projects["NOPREFIX"], rows)
		# Is Active = No and a non-SCRUM project type are both excluded outright.
		self.assertNotIn(self.projects["INACTIVE"], rows)
		self.assertNotIn(self.projects["NOTSCRUM"], rows)

	# ------------------------------------------------------------------
	# Show in Roadmap opt-in (WI-002045)
	# ------------------------------------------------------------------
	def test_only_projects_shown_in_roadmap_get_a_lane(self):
		"""Show in Roadmap is opt-in: No and blank both keep a project off the board."""
		rows = self._rows(self._board())

		self.assertIn(self.projects["OPEN"], rows)
		self.assertNotIn(self.projects["HIDDEN"], rows, "Show in Roadmap = No must be excluded")
		self.assertNotIn(self.projects["UNSET"], rows, "blank must not be treated as Yes")

	def test_show_in_roadmap_filter_cannot_be_bypassed_by_naming_the_project(self):
		"""`lane` comes from the client, so it must not reach an opted-out project."""
		for key in ("HIDDEN", "UNSET"):
			rows = self._rows(get_roadmap_data(lane=json.dumps([self.projects[key]])))
			self.assertEqual(rows, {}, f"{key} was reachable via lane")

	def test_opting_a_project_in_gives_it_a_lane(self):
		"""Flipping the flag to Yes is all it takes — no other change required."""
		hidden = self.projects["HIDDEN"]
		self.assertNotIn(hidden, self._rows(self._board()))

		frappe.db.set_value("Project", hidden, ROADMAP_FLAG_FIELD, "Yes")
		frappe.db.commit()

		self.assertIn(hidden, self._rows(self._board()))

	def test_filter_project_list_excludes_opted_out_projects(self):
		"""The picker must offer exactly the projects the board can show."""
		listed = {p["name"] for p in get_scrum_projects() if p["label"].startswith(TEST_PREFIX)}

		self.assertIn(self.projects["OPEN"], listed)
		self.assertNotIn(self.projects["HIDDEN"], listed)
		self.assertNotIn(self.projects["UNSET"], listed)

	def test_create_missing_sprints_skips_opted_out_projects(self):
		"""An off-board project must not be fillable even if the client names it."""
		result = create_missing_sprints(
			future_count=2, lanes=json.dumps([self.projects["HIDDEN"]])
		)

		self.assertEqual(result["created_count"], 0)

	def test_move_into_empty_slot_of_opted_out_project_is_refused(self):
		"""Auto-creating a sprint re-checks board membership, not just the type."""
		sprint = self._make_sprint("OPEN", align_to_sprint_start(getdate()))
		wi = self._make_work_item(f"{TEST_PREFIX} guarded", sprint)
		ws = align_to_sprint_start(add_days(getdate(), 8))

		with self.assertRaises(frappe.ValidationError):
			move_work_item(
				work_item=wi,
				lane=self.projects["HIDDEN"],
				window_start=str(ws),
				window_end=str(add_days(ws, SPRINT_SPAN_DAYS)),
			)

	def test_row_carries_prefix_and_project_status(self):
		rows = self._rows(self._board())

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

	def test_empty_project_status_does_not_narrow_the_picked_lanes(self):
		"""With projects named, no status ticked leaves every one of their statuses."""
		picked = json.dumps([self.projects["OPEN"], self.projects["COMPLETED"]])
		for empty in (None, "", [], "[]"):
			rows = self._rows(get_roadmap_data(lane=picked, project_status=empty))
			self.assertIn(self.projects["COMPLETED"], rows, f"failed for {empty!r}")

	def test_unknown_status_values_are_dropped(self):
		"""A forged status must not widen the query past the three real ones."""
		rows = self._rows(get_roadmap_data(project_status=json.dumps(["Open", "Bogus"])))
		self.assertIn(self.projects["OPEN"], rows)
		self.assertNotIn(self.projects["COMPLETED"], rows)

	# ------------------------------------------------------------------
	# Nothing loads until projects are picked
	# ------------------------------------------------------------------
	def test_an_untouched_filter_loads_nothing(self):
		"""The state the page opens in: no lanes, no columns, no cells."""
		for empty in (None, "", [], "[]"):
			data = get_roadmap_data(project_status=empty, lane=empty)
			self.assertEqual(data["rows"], [], f"failed for {empty!r}")
			self.assertEqual(data["columns"], [], f"failed for {empty!r}")
			self.assertEqual(data["cells"], {}, f"failed for {empty!r}")
			self.assertEqual(data["missing_count"], 0, f"failed for {empty!r}")

	def test_picking_a_project_loads_its_sprints_and_work_items(self):
		start = align_to_sprint_start(getdate())
		sprint = self._make_sprint("OPEN", start)
		wi = self._make_work_item(f"{TEST_PREFIX} picked story", sprint, story_points=5)

		data = get_roadmap_data(lane=json.dumps([self.projects["OPEN"]]))
		cell = data["cells"][f"{self.projects['OPEN']}::{getdate(start).isoformat()}"]

		self.assertEqual(set(self._rows(data)), {self.projects["OPEN"]})
		self.assertEqual(cell["sprint"], sprint)
		self.assertIn(wi, [item["name"] for item in cell["work_items"]])

	def test_picking_a_status_loads_the_projects_in_it(self):
		"""Either half of the filter is a selection — a status is a bulk pick."""
		rows = self._rows(get_roadmap_data(project_status=json.dumps(["Cancelled"])))

		self.assertEqual(set(rows), {self.projects["CANCELLED"]})

	def test_an_unpicked_project_is_left_out(self):
		"""The point of the story: no lane for a project the user did not ask for."""
		rows = self._rows(get_roadmap_data(lane=json.dumps([self.projects["OPEN"]])))

		self.assertNotIn(self.projects["COMPLETED"], rows)
		self.assertNotIn(self.projects["CANCELLED"], rows)

	def test_a_forged_filter_that_names_nothing_real_loads_nothing(self):
		"""Unknown statuses and unreadable projects both reduce to no selection."""
		data = get_roadmap_data(project_status=json.dumps(["Bogus"]))
		self.assertEqual(data["rows"], [])

	def test_create_missing_sprints_creates_nothing_without_a_selection(self):
		"""No projects picked and no lanes ticked must not fill every project."""
		result = create_missing_sprints(future_count=2)

		self.assertEqual(result["created_count"], 0)
		self.assertEqual(
			frappe.get_all("Sprint", filters={"sprint_prefix": ("like", f"{TEST_PREFIX}%")}),
			[],
		)

	# ------------------------------------------------------------------
	# Project half of the same multi-select (WI-002020)
	# ------------------------------------------------------------------
	def test_lane_accepts_several_projects_as_json(self):
		"""Picking projects in the filter pins the board to exactly those lanes."""
		picked = [self.projects["OPEN"], self.projects["CANCELLED"]]
		rows = self._rows(get_roadmap_data(lane=json.dumps(picked)))

		self.assertEqual(set(rows), set(picked))

	def test_empty_lane_shows_every_project_of_the_ticked_statuses(self):
		"""The lane half may be empty as long as the status half carries the selection."""
		for empty in (None, "", [], "[]"):
			rows = self._rows(get_roadmap_data(project_status=ALL_STATUSES, lane=empty))
			self.assertIn(self.projects["COMPLETED"], rows, f"failed for {empty!r}")

	def test_lane_and_status_narrow_together(self):
		"""The two halves AND: a project outside the ticked statuses drops out."""
		picked = json.dumps([self.projects["OPEN"], self.projects["COMPLETED"]])

		rows = self._rows(get_roadmap_data(lane=picked, project_status=json.dumps(["Open"])))
		self.assertEqual(set(rows), {self.projects["OPEN"]})

		# ...to the point of an empty board when the two disagree entirely.
		rows = self._rows(
			get_roadmap_data(
				lane=json.dumps([self.projects["OPEN"]]),
				project_status=json.dumps(["Cancelled"]),
			)
		)
		self.assertEqual(rows, {})

	def test_lane_cannot_reach_a_non_board_project(self):
		"""Naming an inactive or non-SCRUM project must not put it on the board."""
		picked = json.dumps(
			[self.projects["OPEN"], self.projects["INACTIVE"], self.projects["NOTSCRUM"], "NO SUCH PROJECT"]
		)
		rows = self._rows(get_roadmap_data(lane=picked))

		self.assertEqual(set(rows), {self.projects["OPEN"]})

	def test_get_scrum_projects_lists_the_board_lanes(self):
		"""The filter's project list must match the rows the board can show."""
		listed = {p["name"]: p for p in get_scrum_projects() if p["label"].startswith(TEST_PREFIX)}

		self.assertEqual(set(listed), set(self._rows(self._board())))
		self.assertEqual(listed[self.projects["COMPLETED"]]["status"], "Completed")
		self.assertEqual(
			listed[self.projects["OPEN"]]["label"], self._project_name("OPEN")
		)

	def test_create_missing_sprints_respects_the_lane_filter(self):
		"""A project filtered off the board cannot be filled, even if ticked."""
		result = create_missing_sprints(
			lane=json.dumps([self.projects["OPEN"]]),
			future_count=2,
			lanes=json.dumps([self.projects["OPEN"], self.projects["COMPLETED"]]),
		)

		self.assertEqual(result["created_count"], 2)
		created = frappe.get_all("Sprint", filters={"name": ("in", result["created"])}, pluck="project")
		self.assertEqual(set(created), {self.projects["OPEN"]})

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

	def test_create_missing_sprints_survives_a_stale_naming_counter(self):
		"""Regression: a lagging series counter used to abort the whole project.

		Sprints restored/imported under forced names leave `tabSeries` behind, so
		`make_autoname` returns a name that already exists and the insert died with
		"Sprint LCR-001 already exists". Naming must skip past the taken numbers.
		"""
		from frappe.model.naming import NamingSeries

		project = self.projects["OPEN"]
		prefix = PROJECTS["OPEN"][3]
		counter = NamingSeries(f"{prefix}-.###")

		# Existing sprints occupying <prefix>-001 … -003 …
		counter.update_counter(0)  # teardown clears the sprints but not the counter
		start = align_to_sprint_start(getdate())
		for i in range(3):
			doc = frappe.get_doc(
				{
					"doctype": "Sprint",
					"project": project,
					"sprint_prefix": prefix,
					"status": "Draft",
					"start_date": add_days(start, -7 * (i + 1)),
					"end_date": add_days(start, -7 * (i + 1) + SPRINT_SPAN_DAYS),
					"sprint_goal": "Occupies a number",
				}
			)
			doc.insert(ignore_permissions=True)

		# … while the counter is rewound to zero, exactly as an import leaves it.
		counter.update_counter(0)
		self.assertTrue(frappe.db.exists("Sprint", f"{prefix}-001"))

		result = create_missing_sprints(future_count=2, lanes=json.dumps([project]))

		self.assertEqual(result["created_count"], 2)
		self.assertEqual(len(set(result["created"])), 2, "generated names must be distinct")
		for name in result["created"]:
			self.assertNotIn(name, (f"{prefix}-001", f"{prefix}-002", f"{prefix}-003"))

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


BACKLOG_PREFIX = "RMBACKLOG"
BACKLOG_PROJECT = f"{BACKLOG_PREFIX} Project"


class TestRoadmapBacklog(FrappeTestCase):
	"""What the Roadmap backlog panel shows, and what can change it.

	By default: unsprinted Work Items that are still Draft or Open and are not
	Epics. Backlog Status on Frappe Agile Settings can put different statuses in
	place of Draft and Open; the sprint and Epic tests are not negotiable.

	The panel follows the board's Projects filter, so every test here names the
	fixture project — an unset filter deliberately returns nothing.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Company", {}, "name")
		cls.configured_status = frappe.db.get_single_value(
			"Frappe Agile Settings", "backlog_status"
		)

	@classmethod
	def tearDownClass(cls):
		cls._write_backlog_status(cls.configured_status or "")
		super().tearDownClass()

	def setUp(self):
		self._cleanup()
		self._write_backlog_status("")
		self.project = self._make_project()
		self.sprint = self._make_sprint()
		frappe.db.commit()

	def tearDown(self):
		self._cleanup()
		self._write_backlog_status("")
		frappe.db.commit()

	# ------------------------------------------------------------------
	# Fixtures
	# ------------------------------------------------------------------
	@classmethod
	def _write_backlog_status(cls, value):
		"""Set Backlog Status without going through validation."""
		frappe.db.set_single_value("Frappe Agile Settings", "backlog_status", value)
		frappe.clear_document_cache("Frappe Agile Settings", "Frappe Agile Settings")

	def _save_backlog_status(self, value):
		"""Set Backlog Status the way a user would, so validation runs."""
		settings = frappe.get_single("Frappe Agile Settings")
		settings.backlog_status = value
		settings.save(ignore_permissions=True)

	def _cleanup(self):
		frappe.db.delete("Work Item", {"title": ("like", f"{BACKLOG_PREFIX}%")})
		sprints = frappe.get_all("Sprint", {"sprint_prefix": BACKLOG_PREFIX}, pluck="name")
		if sprints:
			frappe.db.delete("Sprint Work Item", {"parent": ("in", sprints)})
			frappe.db.delete("Sprint", {"name": ("in", sprints)})
		projects = frappe.get_all("Project", {"project_name": BACKLOG_PROJECT}, pluck="name")
		if projects:
			frappe.db.delete("Project", {"name": ("in", projects)})

	def _make_project(self):
		doc = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": BACKLOG_PROJECT,
				"project_type": "SCRUM Project",
				"is_active": "Yes",
				"status": "Open",
				"custom_sprint_prefix": BACKLOG_PREFIX,
				ROADMAP_FLAG_FIELD: "Yes",
				"company": self.company,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_sprint(self):
		start = align_to_sprint_start(getdate())
		doc = frappe.get_doc(
			{
				"doctype": "Sprint",
				"project": self.project,
				"sprint_prefix": BACKLOG_PREFIX,
				"status": "Draft",
				"start_date": start,
				"end_date": add_days(start, SPRINT_SPAN_DAYS),
				"sprint_goal": "Backlog test",
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _set_status(self, name, status):
		"""Force the stored status.

		A newly inserted Work Item lands on Draft whatever status was asked for,
		so the status a test wants has to be written afterwards. These tests are
		about which rows the backlog query returns, not about how an item reaches
		a status.
		"""
		frappe.db.set_value(
			"Work Item",
			name,
			{"status": status, "workflow_state": status},
			update_modified=False,
		)

	def _sprinted(self, title, status="Open", work_item_type="User Story"):
		"""A Work Item sitting on the fixture sprint."""
		doc = frappe.get_doc(
			{
				"doctype": "Work Item",
				"work_item_type": work_item_type,
				"title": f"{BACKLOG_PREFIX} {title}",
				"sprint": self.sprint,
				"story_points": 3,
				"status": status,
				"workflow_state": status,
			}
		)
		doc.insert(ignore_permissions=True)
		self._set_status(doc.name, status)
		return doc.name

	def _unsprinted(self, title, status="Open", work_item_type="User Story"):
		"""A Work Item in the backlog — no sprint.

		Work Item.validate refuses to save a non-Epic without a sprint, so the
		item is created on the fixture sprint and then detached in the database,
		which is how the unsprinted items on real sites came to exist.
		"""
		if work_item_type == "Epic":
			doc = frappe.get_doc(
				{
					"doctype": "Work Item",
					"work_item_type": "Epic",
					"title": f"{BACKLOG_PREFIX} {title}",
					"status": status,
					"workflow_state": status,
				}
			)
			doc.insert(ignore_permissions=True)
			self._set_status(doc.name, status)
			return doc.name

		name = self._sprinted(title, status=status, work_item_type=work_item_type)
		frappe.db.delete("Sprint Work Item", {"work_item": name})
		frappe.db.set_value("Work Item", name, "sprint", None, update_modified=False)
		return name

	def _backlog_names(self, **kwargs):
		"""Only the fixture items — the panel lists the site's real backlog too."""
		kwargs.setdefault("lane", json.dumps([self.project]))
		return [
			row["name"]
			for row in get_unassigned_work_items(**kwargs)
			if (row["title"] or "").startswith(BACKLOG_PREFIX)
		]

	def _projected(self, title, project, status="Open"):
		"""An unsprinted Work Item that does carry a project."""
		name = self._unsprinted(title, status=status)
		frappe.db.set_value("Work Item", name, "project", project, update_modified=False)
		return name

	# ------------------------------------------------------------------
	# The panel follows the Projects filter
	# ------------------------------------------------------------------
	def test_the_backlog_is_empty_until_a_project_is_picked(self):
		self._unsprinted("waiting on a pick")

		for empty in (None, "", [], "[]"):
			self.assertEqual(
				get_unassigned_work_items(project_status=empty, lane=empty),
				[],
				f"failed for {empty!r}",
			)

	def test_picking_the_project_loads_its_backlog(self):
		item = self._projected("belongs here", self.project)

		self.assertIn(item, self._backlog_names())

	def test_another_projects_backlog_is_left_out(self):
		other = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": f"{BACKLOG_PROJECT} OTHER",
				"project_type": "SCRUM Project",
				"is_active": "Yes",
				"status": "Open",
				"custom_sprint_prefix": f"{BACKLOG_PREFIX}O",
				ROADMAP_FLAG_FIELD: "Yes",
				"company": self.company,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Project", other.name, force=True)
		item = self._projected("belongs elsewhere", other.name)

		self.assertNotIn(item, self._backlog_names())
		self.assertIn(item, self._backlog_names(lane=json.dumps([other.name])))

	def test_items_with_no_project_stay_reachable(self):
		"""Unsprinted work usually carries no project; it must still be filable."""
		item = self._unsprinted("no project at all")

		self.assertIn(item, self._backlog_names())

	# ------------------------------------------------------------------
	# What the backlog holds
	# ------------------------------------------------------------------
	def test_draft_and_open_unsprinted_items_are_listed(self):
		draft = self._unsprinted("draft story", status="Draft")
		open_item = self._unsprinted("open story", status="Open")
		names = self._backlog_names()
		self.assertIn(draft, names)
		self.assertIn(open_item, names)

	def test_a_bug_and_a_task_are_listed_too(self):
		bug = self._unsprinted("a bug", work_item_type="Bug")
		task = self._unsprinted("a task", work_item_type="Task")
		names = self._backlog_names()
		self.assertIn(bug, names)
		self.assertIn(task, names)

	def test_items_on_a_sprint_are_not_listed(self):
		"""The backlog is what has not been scheduled."""
		scheduled = self._sprinted("already scheduled", status="Open")
		self.assertNotIn(scheduled, self._backlog_names())

	def test_epics_are_not_listed(self):
		"""Epics are containers, not schedulable work."""
		epic = self._unsprinted("an epic", status="Open", work_item_type="Epic")
		self.assertNotIn(epic, self._backlog_names())

	def test_work_already_under_way_is_not_listed(self):
		"""Anything past Open has been picked up, so it is no longer backlog."""
		started = self._unsprinted("in progress", status="In Progress")
		staging = self._unsprinted("in staging", status="In Staging")
		review = self._unsprinted("pending review", status="Pending Review")
		names = self._backlog_names()
		self.assertNotIn(started, names)
		self.assertNotIn(staging, names)
		self.assertNotIn(review, names)

	def test_finished_and_rejected_work_is_not_listed(self):
		done = self._unsprinted("done", status="Done")
		rejected = self._unsprinted("rejected", status="Rejected")
		names = self._backlog_names()
		self.assertNotIn(done, names)
		self.assertNotIn(rejected, names)

	def test_newest_edited_item_comes_first(self):
		first = self._unsprinted("edited first", status="Open")
		second = self._unsprinted("edited second", status="Open")
		names = self._backlog_names()
		self.assertLess(names.index(second), names.index(first))

	# ------------------------------------------------------------------
	# Backlog Status: the statuses are a default, not a fixture
	# ------------------------------------------------------------------
	def test_a_blank_backlog_status_falls_back_to_draft_and_open(self):
		self._write_backlog_status("")
		self.assertEqual(get_backlog_statuses(), list(DEFAULT_BACKLOG_STATUSES))

	def test_a_configured_status_replaces_the_defaults(self):
		staging = self._unsprinted("in staging", status="In Staging")
		draft = self._unsprinted("draft", status="Draft")

		self._write_backlog_status("In Staging")
		names = self._backlog_names()
		self.assertIn(staging, names)
		self.assertNotIn(draft, names, "Draft is a default, so a configured status must replace it")

	def test_several_statuses_can_be_configured_at_once(self):
		draft = self._unsprinted("draft", status="Draft")
		started = self._unsprinted("in progress", status="In Progress")
		open_item = self._unsprinted("open", status="Open")

		self._write_backlog_status("Draft, In Progress")
		names = self._backlog_names()
		self.assertIn(draft, names)
		self.assertIn(started, names)
		self.assertNotIn(open_item, names)

	def test_a_configured_status_cannot_pull_in_epics_or_sprinted_work(self):
		"""Only the statuses are configurable — the other two tests always hold."""
		epic = self._unsprinted("an epic", status="Open", work_item_type="Epic")
		scheduled = self._sprinted("already scheduled", status="Open")

		self._write_backlog_status("Open")
		names = self._backlog_names()
		self.assertNotIn(epic, names)
		self.assertNotIn(scheduled, names)

	def test_a_status_that_does_not_exist_is_refused_on_save(self):
		with self.assertRaises(frappe.ValidationError):
			self._save_backlog_status("Nonsense Status")

	def test_one_bad_status_in_a_list_is_refused_on_save(self):
		with self.assertRaises(frappe.ValidationError):
			self._save_backlog_status("Draft, Nonsense Status")

	def test_a_valid_list_is_stored_tidied(self):
		self._save_backlog_status("  Draft ,In Progress  ")
		self.assertEqual(
			frappe.db.get_single_value("Frappe Agile Settings", "backlog_status"),
			"Draft, In Progress",
		)
