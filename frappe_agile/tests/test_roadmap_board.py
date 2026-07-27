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
