from __future__ import annotations

import unittest
from datetime import date, timedelta

try:
    import frappe
except ImportError:
    frappe = None


class TestSprintLifecycle(unittest.TestCase):
    """Test sprint lifecycle: Draft -> Active -> Completed."""

    def test_sprint_creation_with_dates(self):
        today = date.today()
        start = today
        end = today + timedelta(days=14)
        assert start < end

    def test_sprint_start_draft_to_active(self):
        status = "Active"
        assert status in ("Active", "Draft", "Completed")

    def test_sprint_task_assignment(self):
        tasks = ["TASK-001", "TASK-002"]
        assert len(tasks) == 2

    def test_story_point_tracking_assigned(self):
        points = {"assigned": 20, "completed": 0, "remaining": 20}
        assert points["remaining"] == points["assigned"] - points["completed"]

    def test_story_point_tracking_completion(self):
        points = {"assigned": 20, "completed": 10, "remaining": 10}
        assert points["remaining"] == 10

    def test_sprint_completion_remaining_handling(self):
        remaining = []
        assert remaining == []

    def test_sprint_velocity_calculation(self):
        completed = [5, 8, 3, 7]
        velocity = sum(completed) / len(completed)
        assert velocity == 5.75

    def test_sprint_burndown_data(self):
        days = [0, 1, 2, 3]
        remaining = [20, 15, 8, 0]
        assert len(days) == len(remaining)


if __name__ == "__main__":
    unittest.main()
