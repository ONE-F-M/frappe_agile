"""End-to-end tests for Roadmap board sprint creation.

Sprint.project is mandatory and Sprint.sprint_prefix is read-only, fetched from
`project.custom_sprint_prefix`. So a Sprint can only be created where the
Project is known — which on the Roadmap means project grouping. Under
sprint-prefix grouping the lane is a bare string that may belong to no project,
so creation is refused with guidance instead of producing an unowned Sprint.

These tests cover both creation paths (the "Create Missing Sprint(s)" bulk
action and the drag-into-an-empty-slot path in move_work_item) plus the
missing_count that drives the button's visibility.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today

from frappe_agile.frappe_agile.doctype.sprint.sprint import (
    SPRINT_SPAN_DAYS,
    align_to_sprint_start,
)
from frappe_agile.frappe_agile.page.roadmap_board.roadmap_board import (
    create_missing_sprints,
    get_roadmap_data,
    get_unassigned_work_items,
    move_work_item,
)
from frappe_agile.tests.fixtures import (
    TEST_PREFIXES,
    delete_test_projects,
    ensure_test_project,
    test_project_name,
)

# A project deliberately left without a Sprint Prefix, to prove it is skipped
# with a reason rather than blowing up the whole batch.
NO_PREFIX_PROJECT = "_Test Agile Project NOPREFIX"


class RoadmapBoardTestCase(FrappeTestCase):
    """create_missing_sprints commits, so rollback cannot be relied on."""

    def setUp(self):
        self._cleanup()
        frappe.db.commit()
        frappe.db.transaction_writes = 0
        self.addCleanup(self._cleanup_and_commit)

    def _cleanup(self):
        sprints = frappe.get_all(
            "Sprint", filters={"sprint_prefix": ("in", TEST_PREFIXES)}, pluck="name"
        )
        projects = [test_project_name(p) for p in TEST_PREFIXES] + [NO_PREFIX_PROJECT]
        sprints += frappe.get_all("Sprint", filters={"project": ("in", projects)}, pluck="name")
        if sprints:
            frappe.db.delete("Sprint Work Item", {"parent": ("in", sprints)})
            frappe.db.delete("Work Item", {"sprint": ("in", sprints)})
            frappe.db.delete("Sprint", {"name": ("in", sprints)})
        frappe.db.delete("Work Item", {"title": ("like", "_Test Roadmap%")})
        delete_test_projects(extra_projects=[NO_PREFIX_PROJECT])

    def _cleanup_and_commit(self):
        self._cleanup()
        frappe.db.commit()

    # --- helpers -----------------------------------------------------------

    def _seed_lane_without_prefix(self):
        """A board lane whose Project has no Sprint Prefix.

        Reached the only way it can be in practice: the Project had a prefix,
        sprints were created under it, and the prefix was then cleared. (A
        Project with no prefix can never get a first Sprint, since sprint_prefix
        is mandatory — so it could not be a lane at all.)
        """
        if not frappe.db.exists("Project", NO_PREFIX_PROJECT):
            frappe.get_doc(
                {
                    "doctype": "Project",
                    "project_name": NO_PREFIX_PROJECT,
                    "status": "Open",
                    "custom_sprint_prefix": "NOPFX",
                }
            ).insert(ignore_permissions=True)
        else:
            frappe.db.set_value(
                "Project", NO_PREFIX_PROJECT, "custom_sprint_prefix", "NOPFX", update_modified=False
            )

        sprint = self._seed_sprint(NO_PREFIX_PROJECT)

        frappe.db.set_value(
            "Project", NO_PREFIX_PROJECT, "custom_sprint_prefix", None, update_modified=False
        )
        return NO_PREFIX_PROJECT, sprint

    def _seed_sprint(self, project, start_date=None):
        """A sprint must already exist for a project to appear as a board lane."""
        ws = align_to_sprint_start(start_date or add_days(today(), -14))
        doc = frappe.get_doc(
            {
                "doctype": "Sprint",
                "project": project,
                "status": "Draft",
                "start_date": ws,
                "end_date": add_days(ws, SPRINT_SPAN_DAYS),
                "sprint_goal": "seed",
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def _make_work_item(self, title, sprint_name):
        wi = frappe.get_doc(
            {
                "doctype": "Work Item",
                "work_item_type": "User Story",
                "title": title,
                "sprint": sprint_name,
                "story_points": 3,
                "workflow_state": "Open",
                "status": "Open",
            }
        )
        wi.insert(ignore_permissions=True)
        return wi


class TestCreateMissingSprints(RoadmapBoardTestCase):
    def test_refused_when_grouped_by_sprint_prefix(self):
        """The old default. A prefix lane does not identify a Project."""
        project = ensure_test_project("TEST")
        self._seed_sprint(project)

        with self.assertRaises(frappe.ValidationError) as ctx:
            create_missing_sprints(group_by="sprint_prefix", future_count=2)
        self.assertIn("grouped by Project", str(ctx.exception))

    def test_refused_for_any_non_project_grouping(self):
        with self.assertRaises(frappe.ValidationError):
            create_missing_sprints(group_by="", future_count=2)

    def test_creates_sprints_carrying_the_project(self):
        project = ensure_test_project("TEST")
        self._seed_sprint(project)

        result = create_missing_sprints(group_by="project", future_count=2)

        self.assertEqual(result["created_count"], 2)
        for name in result["created"]:
            sprint = frappe.get_doc("Sprint", name)
            self.assertEqual(sprint.project, project)
            # The whole point: the prefix is derived, never passed in.
            self.assertEqual(sprint.sprint_prefix, "TEST")
            self.assertEqual(sprint.status, "Draft")
            self.assertTrue(sprint.name.startswith("TEST-"))

    def test_created_sprints_land_on_upcoming_windows(self):
        project = ensure_test_project("TEST")
        self._seed_sprint(project)

        result = create_missing_sprints(group_by="project", future_count=3)

        first = align_to_sprint_start(add_days(getdate(), 1))
        expected = {add_days(first, 7 * i) for i in range(3)}
        actual = {
            getdate(frappe.db.get_value("Sprint", n, "start_date")) for n in result["created"]
        }
        self.assertEqual(actual, expected)

    def test_is_idempotent(self):
        project = ensure_test_project("TEST")
        self._seed_sprint(project)

        first = create_missing_sprints(group_by="project", future_count=2)
        self.assertEqual(first["created_count"], 2)

        second = create_missing_sprints(group_by="project", future_count=2)
        self.assertEqual(second["created_count"], 0, "re-running must not duplicate sprints")

    def test_project_without_prefix_is_skipped_not_fatal(self):
        """One unprefixed project must not deny every other project its sprints."""
        good = ensure_test_project("TEST")
        self._seed_sprint(good)
        bad, _ = self._seed_lane_without_prefix()

        result = create_missing_sprints(group_by="project", future_count=2)

        # Only the two windows for the prefixed test project. Any other lane on
        # the site without a prefix is skipped too, so assert membership rather
        # than an exact list.
        self.assertEqual(result["created_count"], 2, "the prefixed project should still be filled")
        skipped = [s["project"] for s in result["skipped"]]
        self.assertIn(bad, skipped)
        self.assertNotIn(good, skipped)
        self.assertEqual(
            frappe.db.count("Sprint", {"project": bad, "start_date": (">", today())}), 0
        )
        for entry in result["skipped"]:
            self.assertIn("Sprint Prefix", entry["reason"])

    def test_lane_selection_restricts_creation(self):
        a = ensure_test_project("ALPHA")
        b = ensure_test_project("BETA")
        self._seed_sprint(a)
        self._seed_sprint(b)

        result = create_missing_sprints(
            group_by="project", future_count=2, lanes=frappe.as_json([a])
        )

        self.assertEqual(result["created_count"], 2)
        projects = {frappe.db.get_value("Sprint", n, "project") for n in result["created"]}
        self.assertEqual(projects, {a})

    def test_forged_lane_outside_the_board_creates_nothing(self):
        project = ensure_test_project("TEST")
        self._seed_sprint(project)

        result = create_missing_sprints(
            group_by="project", future_count=2, lanes=frappe.as_json(["_Not On The Board"])
        )
        self.assertEqual(result["created_count"], 0)


class TestMissingCount(RoadmapBoardTestCase):
    """missing_count drives the "Create Missing Sprint(s)" button's visibility."""

    def test_reported_under_project_grouping(self):
        project = ensure_test_project("TEST")
        self._seed_sprint(project)

        data = get_roadmap_data(group_by="project", future_count=2)
        self.assertEqual(data["missing_count"], 2)

    def test_zero_under_prefix_grouping(self):
        """Nothing can be created there, so nothing may be offered."""
        project = ensure_test_project("TEST")
        self._seed_sprint(project)

        data = get_roadmap_data(group_by="sprint_prefix", future_count=2)
        self.assertEqual(data["missing_count"], 0)

    def test_drops_to_zero_once_filled(self):
        project = ensure_test_project("TEST")
        self._seed_sprint(project)

        create_missing_sprints(group_by="project", future_count=2)
        data = get_roadmap_data(group_by="project", future_count=2)
        self.assertEqual(data["missing_count"], 0)

    def test_project_without_prefix_is_not_counted(self):
        self._seed_lane_without_prefix()

        data = get_roadmap_data(group_by="project", future_count=2)
        self.assertEqual(data["missing_count"], 0, "an uncreatable lane must not be offered")


class TestMoveWorkItem(RoadmapBoardTestCase):
    def _future_window(self):
        ws = align_to_sprint_start(add_days(today(), 1))
        return ws, add_days(ws, SPRINT_SPAN_DAYS)

    def test_drop_into_empty_slot_creates_sprint_for_the_project(self):
        project = ensure_test_project("TEST")
        seed = self._seed_sprint(project)
        wi = self._make_work_item("_Test Roadmap Move", seed.name)
        ws, we = self._future_window()

        result = move_work_item(
            work_item=wi.name,
            target_sprint=None,
            lane=project,
            group_by="project",
            window_start=ws,
            window_end=we,
        )

        self.assertTrue(result["created"])
        created = frappe.get_doc("Sprint", result["target_sprint"])
        self.assertEqual(created.project, project)
        self.assertEqual(created.sprint_prefix, "TEST")
        self.assertEqual(getdate(created.start_date), getdate(ws))

        wi.reload()
        self.assertEqual(wi.sprint, created.name)
        # Work Item.project is fetched from the sprint, completing the hierarchy.
        self.assertEqual(wi.project, project)

    def test_drop_into_empty_slot_reuses_an_existing_sprint(self):
        project = ensure_test_project("TEST")
        seed = self._seed_sprint(project)
        ws, we = self._future_window()
        existing = self._seed_sprint(project, start_date=ws)
        wi = self._make_work_item("_Test Roadmap Reuse", seed.name)

        result = move_work_item(
            work_item=wi.name,
            target_sprint=None,
            lane=project,
            group_by="project",
            window_start=ws,
            window_end=we,
        )

        self.assertFalse(result["created"])
        self.assertEqual(result["target_sprint"], existing.name)

    def test_drop_under_prefix_grouping_is_refused_and_creates_nothing(self):
        """The reported bug: this used to raise a bare MandatoryError."""
        project = ensure_test_project("TEST")
        seed = self._seed_sprint(project)
        wi = self._make_work_item("_Test Roadmap Refused", seed.name)
        ws, we = self._future_window()
        before = frappe.db.count("Sprint")

        with self.assertRaises(frappe.ValidationError) as ctx:
            move_work_item(
                work_item=wi.name,
                target_sprint=None,
                lane="TEST",
                group_by="sprint_prefix",
                window_start=ws,
                window_end=we,
            )

        message = str(ctx.exception)
        self.assertIn("grouped by Project", message)
        self.assertNotIn("MandatoryError", message)
        self.assertEqual(frappe.db.count("Sprint"), before, "no Sprint may be created")
        wi.reload()
        self.assertEqual(wi.sprint, seed.name, "the work item must not move")

    def test_drop_for_project_without_prefix_gives_an_actionable_error(self):
        good = ensure_test_project("TEST")
        seed = self._seed_sprint(good)
        bad, _ = self._seed_lane_without_prefix()
        wi = self._make_work_item("_Test Roadmap NoPrefix", seed.name)
        ws, we = self._future_window()

        with self.assertRaises(frappe.ValidationError) as ctx:
            move_work_item(
                work_item=wi.name,
                target_sprint=None,
                lane=bad,
                group_by="project",
                window_start=ws,
                window_end=we,
            )
        self.assertIn("Sprint Prefix", str(ctx.exception))

    def test_move_to_an_explicit_sprint_still_works_under_prefix_grouping(self):
        """Only auto-creation is gated; moving into an existing sprint is not."""
        project = ensure_test_project("TEST")
        seed = self._seed_sprint(project)
        target = self._seed_sprint(project, start_date=add_days(today(), -7))
        wi = self._make_work_item("_Test Roadmap Explicit", seed.name)

        result = move_work_item(
            work_item=wi.name, target_sprint=target.name, group_by="sprint_prefix"
        )

        self.assertEqual(result["target_sprint"], target.name)
        wi.reload()
        self.assertEqual(wi.sprint, target.name)


class TestUnassignedWorkItems(RoadmapBoardTestCase):
    """The Roadmap's backlog panel calls `get_unassigned_work_items`.

    The method was removed by the sprint-cleanup revert (af3b7cd) while the JS
    that calls it was later merged back, leaving the panel dead with
    "module has no attribute 'get_unassigned_work_items'". These tests pin the
    contract the client actually depends on so the pair cannot drift apart
    again silently.
    """

    def setUp(self):
        super().setUp()
        # The site carries real unsprinted work items, so every assertion below
        # is about membership and relative order — never an exact result set.
        self._restore_backlog_status = frappe.db.get_single_value(
            "Frappe Agile Settings", "backlog_status"
        )
        self._set_backlog_status(None)
        self.addCleanup(lambda: self._set_backlog_status(self._restore_backlog_status))

    def _set_backlog_status(self, value):
        frappe.db.set_single_value("Frappe Agile Settings", "backlog_status", value)

    def _make_backlog_item(self, title, work_item_type="User Story", status="Open"):
        """An unsprinted Work Item — what the backlog panel is for.

        Two quirks of Work Item are worked around here rather than in the code
        under test: the workflow engine stamps its own default state on insert
        (so a requested `status` has to be forced afterwards), and story points
        are rejected outright on Epics.
        """
        payload = {
            "doctype": "Work Item",
            "work_item_type": work_item_type,
            "title": title,
            "project": ensure_test_project("TEST"),
        }
        if work_item_type != "Epic":
            payload["story_points"] = 2

        wi = frappe.get_doc(payload)
        wi.insert(ignore_permissions=True)

        if wi.status != status:
            frappe.db.set_value(
                "Work Item",
                wi.name,
                {"status": status, "workflow_state": status},
                update_modified=False,
            )
            wi.reload()
        return wi

    def _names(self, **kwargs):
        return [row["name"] for row in get_unassigned_work_items(**kwargs)]

    # --- the regression itself ---------------------------------------------

    def test_module_exposes_the_whitelisted_method(self):
        """The exact failure that was reported: the client resolves this method
        by dotted path, so its absence is an AttributeError at call time rather
        than anything the linter or the tests would otherwise notice."""
        from frappe_agile.frappe_agile.page.roadmap_board import roadmap_board

        method = getattr(roadmap_board, "get_unassigned_work_items", None)
        self.assertIsNotNone(method, "roadmap_board.js calls this by dotted path")
        self.assertIn(method, frappe.whitelisted, "must be callable from the client")

    # --- what belongs in the backlog ---------------------------------------

    def test_returns_items_with_no_sprint(self):
        wi = self._make_backlog_item("_Test Roadmap Backlog Loose")
        self.assertIn(wi.name, self._names())

    def test_excludes_items_already_on_a_sprint(self):
        sprint = self._seed_sprint(ensure_test_project("TEST"))
        wi = self._make_work_item("_Test Roadmap Backlog Sprinted", sprint.name)
        self.assertNotIn(wi.name, self._names())

    def test_excludes_epics(self):
        """Epics are containers, not schedulable work — they must never be
        draggable onto a sprint from the backlog."""
        epic = self._make_backlog_item("_Test Roadmap Backlog Epic", work_item_type="Epic")
        self.assertNotIn(epic.name, self._names())

    def test_includes_every_schedulable_type(self):
        made = {
            t: self._make_backlog_item(f"_Test Roadmap Backlog {t}", work_item_type=t).name
            for t in ("Task", "User Story", "Bug")
        }
        names = self._names()
        for work_item_type, name in made.items():
            self.assertIn(name, names, f"{work_item_type} should appear in the backlog")

    # --- ordering and paging ------------------------------------------------

    def test_newest_modified_first(self):
        older = self._make_backlog_item("_Test Roadmap Backlog Older")
        newer = self._make_backlog_item("_Test Roadmap Backlog Newer")
        # Insert order does not guarantee distinct timestamps; force the gap so
        # the assertion is about the ordering rule, not about clock resolution.
        frappe.db.set_value(
            "Work Item", older.name, "modified", add_days(today(), -3), update_modified=False
        )
        frappe.db.set_value(
            "Work Item", newer.name, "modified", today(), update_modified=False
        )

        names = self._names()
        self.assertLess(
            names.index(newer.name), names.index(older.name), "most recently edited first"
        )

    def test_limit_is_respected(self):
        for i in range(3):
            self._make_backlog_item(f"_Test Roadmap Backlog Limit {i}")
        self.assertLessEqual(len(self._names(limit=2)), 2)

    # --- the Backlog Status setting ----------------------------------------

    def test_blank_backlog_status_shows_every_status(self):
        open_item = self._make_backlog_item("_Test Roadmap Backlog Open", status="Open")
        draft_item = self._make_backlog_item("_Test Roadmap Backlog Draft", status="Draft")

        names = self._names()
        self.assertIn(open_item.name, names)
        self.assertIn(draft_item.name, names)

    def test_backlog_status_narrows_the_panel(self):
        open_item = self._make_backlog_item("_Test Roadmap Backlog Keep", status="Open")
        draft_item = self._make_backlog_item("_Test Roadmap Backlog Drop", status="Draft")

        self._set_backlog_status("Open")

        names = self._names()
        self.assertIn(open_item.name, names)
        self.assertNotIn(draft_item.name, names)

    # --- the contract the client reads --------------------------------------

    def test_payload_carries_every_field_the_client_renders(self):
        """roadmap_board.js reads these keys directly in _backlog_item_html; a
        rename here shows up as a blank card rather than an error."""
        wi = self._make_backlog_item("_Test Roadmap Backlog Shape")

        row = next(r for r in get_unassigned_work_items() if r["name"] == wi.name)

        self.assertEqual(row["title"], "_Test Roadmap Backlog Shape")
        self.assertEqual(row["type"], "User Story")
        self.assertEqual(row["status"], "Open")
        self.assertEqual(row["story_points"], 2)
        self.assertTrue(row["modified"], "prettyDate() needs a modified timestamp")
        self.assertFalse(row["accepted"], "an Open item is not accepted")

    def test_title_falls_back_to_the_name(self):
        """The card would otherwise render an empty row."""
        wi = self._make_backlog_item("_Test Roadmap Backlog Untitled")
        frappe.db.set_value("Work Item", wi.name, "title", "", update_modified=False)

        row = next(r for r in get_unassigned_work_items() if r["name"] == wi.name)
        self.assertEqual(row["title"], wi.name)


class TestBacklogStatusValidation(FrappeTestCase):
    """Backlog Status is free-text but drives a status filter, so a typo would
    silently empty the panel rather than fail."""

    def tearDown(self):
        frappe.db.rollback()

    def test_rejects_a_status_that_does_not_exist(self):
        settings = frappe.get_single("Frappe Agile Settings")
        settings.backlog_status = "Not A Real Status"
        with self.assertRaises(frappe.ValidationError) as ctx:
            settings.validate_backlog_status()
        self.assertIn("not a valid Work Item status", str(ctx.exception))

    def test_accepts_a_real_status(self):
        from frappe_agile.frappe_agile.doctype.frappe_agile_settings.frappe_agile_settings import (
            work_item_status_options,
        )

        settings = frappe.get_single("Frappe Agile Settings")
        settings.backlog_status = work_item_status_options()[0]
        settings.validate_backlog_status()  # must not raise

    def test_blank_is_allowed(self):
        settings = frappe.get_single("Frappe Agile Settings")
        settings.backlog_status = None
        settings.validate_backlog_status()  # must not raise
