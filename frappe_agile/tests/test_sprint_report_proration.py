# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

"""Working-day proration in the two sprint performance reports.

A velocity target is earned over the days a person could actually work: the
sprint's calendar days, less their weekly offs, less public holidays, less
approved leave. These tests cover the public-holiday half of that, the leave
half, and the rule that a day off is never charged twice.

The sprint under test is the standard Wed → Tue window of 26 Aug – 1 Sep 2026,
against a Holiday List whose weekly offs are Friday and Saturday and which
carries one public holiday, Thursday 27 Aug:

    Wed 26  working        Sun 30  working
    Thu 27  public holiday Mon 31  working
    Fri 28  weekly off     Tue  1  working
    Sat 29  weekly off

7 calendar days − 2 weekly offs = 5 working days, one of them a public holiday.

Fixtures are torn down by name rather than by rollback: inserting an Employee
commits part-way through, so a rollback leaves records behind.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, getdate

from frappe_agile.frappe_agile.report.proration import get_period_breakdown, get_proration
from frappe_agile.frappe_agile.report.sprint_report_per_business_analyst.sprint_report_per_business_analyst import (
	execute as ba_report,
)
from frappe_agile.frappe_agile.report.sprint_report_per_developer.sprint_report_per_developer import (
	execute as developer_report,
)

PREFIX = "_Test Proration"
HOLIDAY_LIST = f"{PREFIX} Holiday List"
LEAVE_TYPE = f"{PREFIX} Leave"
LEAVE_TYPE_INCL_HOLIDAY = f"{PREFIX} Leave Incl Holidays"
PROJECT = f"{PREFIX} Project"
SPRINT_PREFIX = "PRORATE"
TITLE_PREFIX = f"{PREFIX} Item"

DEV_USER = "_test_proration_dev@example.com"
BA_USER = "_test_proration_ba@example.com"
# A User with no Employee record at all — nothing to prorate against.
UNLINKED_USER = "_test_proration_unlinked@example.com"

# The sprint under test, and the following week which has no public holiday.
PERIOD = ("2026-08-26", "2026-09-01")
CLEAN_PERIOD = ("2026-09-02", "2026-09-08")
PUBLIC_HOLIDAY = "2026-08-27"

WORKING_DAYS = 5
DEV_VELOCITY = 80.0
BA_VELOCITY = 100.0


class TestSprintReportProration(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._cleanup()
		cls._make_holiday_list()
		cls._make_leave_types()
		cls.dev_employee = cls._make_employee(DEV_USER)
		cls.ba_employee = cls._make_employee(BA_USER)
		cls._make_user(UNLINKED_USER)
		cls.project = cls._make_project()
		cls.previous_velocities = cls._set_velocities(DEV_VELOCITY, BA_VELOCITY)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls._set_velocities(*cls.previous_velocities)
		cls._cleanup()
		super().tearDownClass()

	def tearDown(self):
		# Leave and sprints are per-test; the calendar and the people are not.
		self._delete_leave_applications()
		self._delete_sprints()
		frappe.db.commit()

	# ------------------------------------------------------------------
	# Fixtures
	# ------------------------------------------------------------------

	@classmethod
	def _cleanup(cls):
		cls._delete_leave_applications()
		cls._delete_sprints()
		cls._delete_project()

		for user in (DEV_USER, BA_USER, UNLINKED_USER):
			for name in frappe.get_all("Employee", {"user_id": user}, pluck="name"):
				frappe.delete_doc("Employee", name, force=True, ignore_permissions=True)
			if frappe.db.exists("User", user):
				frappe.delete_doc("User", user, force=True, ignore_permissions=True)
		cls._delete_contacts()

		for leave_type in (LEAVE_TYPE, LEAVE_TYPE_INCL_HOLIDAY):
			if frappe.db.exists("Leave Type", leave_type):
				frappe.delete_doc("Leave Type", leave_type, force=True, ignore_permissions=True)

		if frappe.db.exists("Holiday List", HOLIDAY_LIST):
			frappe.delete_doc("Holiday List", HOLIDAY_LIST, force=True, ignore_permissions=True)

		frappe.db.commit()

	@classmethod
	def _delete_leave_applications(cls):
		employees = frappe.get_all(
			"Employee", {"user_id": ("in", [DEV_USER, BA_USER, UNLINKED_USER])}, pluck="name"
		)
		if employees:
			frappe.db.delete("Leave Application", {"employee": ("in", employees)})

	@classmethod
	def _delete_sprints(cls):
		frappe.db.delete("Work Item", {"title": ("like", f"{TITLE_PREFIX}%")})
		sprints = frappe.get_all("Sprint", {"sprint_prefix": SPRINT_PREFIX}, pluck="name")
		if sprints:
			frappe.db.delete("Sprint Work Item", {"parent": ("in", sprints)})
			frappe.db.delete("Sprint", {"sprint_prefix": SPRINT_PREFIX})

	@classmethod
	def _delete_contacts(cls):
		"""Saving a User or an Employee creates a Contact, and deleting them
		leaves it behind. A second run then trips over the duplicate email."""
		# One Contact comes from the User, another from the Employee, and neither
		# carries a link back — the shared first name is what identifies them.
		first_names = [user.split("@")[0] for user in (DEV_USER, BA_USER, UNLINKED_USER)]
		for contact in frappe.get_all("Contact", {"first_name": ("in", first_names)}, pluck="name"):
			if frappe.db.exists("Contact", contact):
				frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True)

	@classmethod
	def _delete_project(cls):
		project = frappe.db.get_value("Project", {"project_name": PROJECT}, "name")
		if project:
			frappe.delete_doc("Project", project, force=True, ignore_permissions=True)

	@classmethod
	def _make_holiday_list(cls):
		"""Friday and Saturday off, plus one public holiday on Thursday 27 Aug."""
		holiday_list = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": HOLIDAY_LIST,
				"from_date": "2026-08-01",
				"to_date": "2026-09-30",
			}
		)

		day = getdate("2026-08-01")
		while day <= getdate("2026-09-30"):
			if day.weekday() in (4, 5):  # Friday, Saturday
				holiday_list.append(
					"holidays",
					{"holiday_date": day, "description": day.strftime("%A"), "weekly_off": 1},
				)
			day = add_days(day, 1)

		holiday_list.append(
			"holidays",
			{"holiday_date": PUBLIC_HOLIDAY, "description": "Test Public Holiday", "weekly_off": 0},
		)
		holiday_list.insert(ignore_permissions=True)

	@classmethod
	def _make_leave_types(cls):
		for leave_type, include_holiday in (
			(LEAVE_TYPE, 0),
			(LEAVE_TYPE_INCL_HOLIDAY, 1),
		):
			frappe.get_doc(
				{
					"doctype": "Leave Type",
					"leave_type_name": leave_type,
					# Leave without pay needs no allocation to be applied for.
					"is_lwp": 1,
					"include_holiday": include_holiday,
				}
			).insert(ignore_permissions=True)

	@classmethod
	def _make_user(cls, user):
		if frappe.db.exists("User", user):
			return
		frappe.get_doc(
			{
				"doctype": "User",
				"email": user,
				"first_name": user.split("@")[0],
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)

	@classmethod
	def _make_employee(cls, user):
		"""An Employee on the test Holiday List, linked to *user*.

		The extra name and salary fields are mandatory on this site's Employee.
		"""
		cls._make_user(user)
		employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": user.split("@")[0],
				"last_name": "Proration",
				"company": frappe.db.get_single_value("Global Defaults", "default_company"),
				"date_of_birth": "1990-05-08",
				"date_of_joining": "2020-01-01",
				"gender": "Female",
				"department": frappe.get_all("Department", pluck="name", limit=1)[0],
				"status": "Active",
				"holiday_list": HOLIDAY_LIST,
				"one_fm_first_name_in_arabic": "اختبار",
				"one_fm_last_name_in_arabic": "اختبار",
				"one_fm_basic_salary": 100,
			}
		)
		employee.insert(ignore_permissions=True)
		# The User link is set afterwards on purpose: with user_id on the insert,
		# ERPNext saves the User as well, which rebuilds its Contact and can fall
		# over on a duplicate primary email. The reports only need the link.
		frappe.db.set_value("Employee", employee.name, "user_id", user, update_modified=False)
		return employee.name

	@classmethod
	def _make_project(cls):
		"""Sprint.sprint_prefix is fetched from the Project, so the prefix lives here."""
		existing = frappe.db.get_value("Project", {"project_name": PROJECT}, "name")
		if existing:
			frappe.db.set_value("Project", existing, "custom_sprint_prefix", SPRINT_PREFIX)
			return existing

		project = frappe.get_doc(
			{"doctype": "Project", "project_name": PROJECT, "custom_sprint_prefix": SPRINT_PREFIX}
		)
		project.insert(ignore_permissions=True)
		return project.name

	@classmethod
	def _set_velocities(cls, developer_velocity, ba_velocity):
		settings = frappe.get_single("Frappe Agile Settings")
		previous = (settings.developer_velocity, settings.ba_velocity)
		settings.developer_velocity = developer_velocity
		settings.ba_velocity = ba_velocity
		settings.save(ignore_permissions=True)
		return previous

	def _make_leave(
		self, leave_type, from_date, to_date, half_day=0, half_day_date=None, employee=None
	):
		leave = frappe.get_doc(
			{
				"doctype": "Leave Application",
				"employee": employee or self.dev_employee,
				"leave_type": leave_type,
				"from_date": from_date,
				"to_date": to_date,
				"half_day": half_day,
				"half_day_date": half_day_date,
				"resumption_date": add_days(getdate(to_date), 1),
				"status": "Approved",
			}
		)
		leave.insert(ignore_permissions=True)
		leave.submit()
		return leave

	def _make_sprint(self, period, business_analyst=None):
		sprint = frappe.get_doc(
			{
				"doctype": "Sprint",
				"sprint_prefix": SPRINT_PREFIX,
				"project": self.project,
				"status": "Draft",
				"start_date": period[0],
				"end_date": period[1],
				"sprint_goal": "Proration test sprint",
				"business_analyst": business_analyst,
			}
		)
		sprint.insert(ignore_permissions=True)
		return sprint

	def _make_work_item(self, sprint, title, story_points, assignee_user=None):
		return frappe.get_doc(
			{
				"doctype": "Work Item",
				"work_item_type": "User Story",
				"title": f"{TITLE_PREFIX} {title}",
				"sprint": sprint,
				"status": "Open",
				"workflow_state": "Open",
				"story_points": story_points,
				"assignee_user": assignee_user,
			}
		).insert(ignore_permissions=True)

	@staticmethod
	def _row_for(rows, field, value):
		return next((row for row in rows if row.get(field) == value), None)

	# ------------------------------------------------------------------
	# The public-holiday half
	# ------------------------------------------------------------------

	def test_weekly_offs_are_not_working_days(self):
		"""A 7-day sprint is 5 working days for someone off on Friday and Saturday."""
		period = get_period_breakdown(self.dev_employee, *CLEAN_PERIOD)
		self.assertEqual(period["working_days"], WORKING_DAYS)

	def test_a_week_without_a_public_holiday_is_left_alone(self):
		period = get_period_breakdown(self.dev_employee, *CLEAN_PERIOD)
		self.assertEqual(period["holiday_days"], 0)
		self.assertEqual(period["leave_days"], 0.0)
		self.assertEqual(period["factor"], 1.0)

	def test_a_public_holiday_cuts_the_target(self):
		"""One holiday out of five working days: four fifths of the target."""
		period = get_period_breakdown(self.dev_employee, *PERIOD)
		self.assertEqual(period["working_days"], WORKING_DAYS)
		self.assertEqual(period["holiday_days"], 1)
		self.assertEqual(period["leave_days"], 0.0)
		self.assertEqual(flt(period["factor"], 4), 0.8)
		self.assertEqual(flt(DEV_VELOCITY * period["factor"], 1), 64.0)

	def test_periods_add_up(self):
		"""Two sprints, one with a holiday: one whole target plus four fifths."""
		factor, working_days, holiday_days, leave_days = get_proration(
			self.dev_employee, [PERIOD, CLEAN_PERIOD]
		)
		self.assertEqual(working_days, 2 * WORKING_DAYS)
		self.assertEqual(holiday_days, 1)
		self.assertEqual(leave_days, 0.0)
		self.assertEqual(flt(DEV_VELOCITY * factor, 1), 144.0)

	# ------------------------------------------------------------------
	# Leave, and not charging a day twice
	# ------------------------------------------------------------------

	def test_leave_and_a_public_holiday_both_count(self):
		"""A holiday plus a day's leave: three of five working days left."""
		self._make_leave(LEAVE_TYPE, "2026-08-31", "2026-08-31")
		period = get_period_breakdown(self.dev_employee, *PERIOD)
		self.assertEqual(period["holiday_days"], 1)
		self.assertEqual(period["leave_days"], 1.0)
		self.assertEqual(flt(period["factor"], 4), 0.6)
		self.assertEqual(flt(DEV_VELOCITY * period["factor"], 1), 48.0)

	def test_half_a_day_of_leave_costs_half_a_day(self):
		self._make_leave(
			LEAVE_TYPE, "2026-08-31", "2026-08-31", half_day=1, half_day_date="2026-08-31"
		)
		period = get_period_breakdown(self.dev_employee, *PERIOD)
		self.assertEqual(period["leave_days"], 0.5)
		self.assertEqual(flt(period["factor"], 4), 0.7)

	def test_leave_on_the_public_holiday_is_not_charged_twice(self):
		"""This Leave Type counts holidays as leave; the day still costs once.

		The leave runs Thu 27 (the public holiday) to Sat 29 (both weekly offs),
		so it costs no working days of its own — the holiday is the only loss.
		"""
		self._make_leave(LEAVE_TYPE_INCL_HOLIDAY, PUBLIC_HOLIDAY, "2026-08-29")
		period = get_period_breakdown(self.dev_employee, *PERIOD)
		self.assertEqual(period["holiday_days"], 1)
		self.assertEqual(period["leave_days"], 0.0)
		self.assertEqual(flt(period["factor"], 4), 0.8)

	def test_leave_outside_the_sprint_is_ignored(self):
		"""Leave the week before the sprint does not touch this sprint's target."""
		self._make_leave(LEAVE_TYPE, "2026-08-17", "2026-08-19")
		period = get_period_breakdown(self.dev_employee, *PERIOD)
		self.assertEqual(period["leave_days"], 0.0)
		self.assertEqual(flt(period["factor"], 4), 0.8)

	def test_leave_across_the_whole_sprint_leaves_nothing(self):
		self._make_leave(LEAVE_TYPE, "2026-08-20", "2026-09-10")
		period = get_period_breakdown(self.dev_employee, *PERIOD)
		self.assertEqual(period["factor"], 0.0)

	# ------------------------------------------------------------------
	# Nothing to prorate against
	# ------------------------------------------------------------------

	def test_no_staff_record_means_no_proration(self):
		period = get_period_breakdown(None, *PERIOD)
		self.assertEqual(period["factor"], 1.0)
		self.assertEqual(period["holiday_days"], 0)
		# Every calendar day counted as a working day, since there is no calendar.
		self.assertEqual(period["working_days"], 7)

	# ------------------------------------------------------------------
	# End to end, through the reports themselves
	# ------------------------------------------------------------------

	def test_developer_report_prorates_the_target(self):
		sprint = self._make_sprint(PERIOD)
		self._make_work_item(sprint.name, "dev", 12, assignee_user=DEV_USER)

		columns, rows = developer_report(
			{"start_date": PERIOD[0], "end_date": PERIOD[1], "developer": DEV_USER}
		)
		fieldnames = [column["fieldname"] for column in columns]
		for fieldname in ("working_days", "public_holidays", "leave_days", "target_points"):
			self.assertIn(fieldname, fieldnames)

		row = self._row_for(rows, "developer", frappe.db.get_value("User", DEV_USER, "full_name"))
		self.assertIsNotNone(row, f"no row for {DEV_USER} in {rows}")
		self.assertEqual(row["working_days"], WORKING_DAYS)
		self.assertEqual(row["public_holidays"], 1)
		self.assertEqual(row["leave_days"], 0.0)
		self.assertEqual(row["target_points"], 64.0)
		self.assertEqual(row["points_scoped"], 12.0)
		# 12 scoped against a 64-point target, not against 80.
		self.assertEqual(row["percentage_target"], 18.75)

	def test_developer_report_leaves_an_unlinked_user_alone(self):
		sprint = self._make_sprint(PERIOD)
		self._make_work_item(sprint.name, "unlinked", 5, assignee_user=UNLINKED_USER)

		_columns, rows = developer_report(
			{"start_date": PERIOD[0], "end_date": PERIOD[1], "developer": UNLINKED_USER}
		)
		row = self._row_for(
			rows, "developer", frappe.db.get_value("User", UNLINKED_USER, "full_name")
		)
		self.assertIsNotNone(row, f"no row for {UNLINKED_USER} in {rows}")
		self.assertEqual(row["public_holidays"], 0)
		self.assertEqual(row["target_points"], DEV_VELOCITY)

	def test_business_analyst_report_prorates_the_target(self):
		sprint = self._make_sprint(PERIOD, business_analyst=BA_USER)
		self._make_work_item(sprint.name, "ba", 10)

		columns, rows = ba_report(
			{"start_date": PERIOD[0], "end_date": PERIOD[1], "business_analyst": BA_USER}
		)
		fieldnames = [column["fieldname"] for column in columns]
		for fieldname in ("working_days", "public_holidays", "leave_days", "expected_velocity"):
			self.assertIn(fieldname, fieldnames)

		row = self._row_for(
			rows, "business_analyst", frappe.db.get_value("User", BA_USER, "full_name")
		)
		self.assertIsNotNone(row, f"no row for {BA_USER} in {rows}")
		self.assertEqual(row["working_days"], WORKING_DAYS)
		self.assertEqual(row["public_holidays"], 1)
		self.assertEqual(row["expected_velocity"], 80.0)  # 100 × 4/5
		self.assertEqual(row["points_scoped"], 10.0)
		self.assertEqual(row["percentage_target"], 12.5)

	def test_business_analyst_report_counts_leave_too(self):
		"""The BA report had no time-off accounting at all before this."""
		self._make_leave(LEAVE_TYPE, "2026-08-31", "2026-08-31", employee=self.ba_employee)

		sprint = self._make_sprint(PERIOD, business_analyst=BA_USER)
		self._make_work_item(sprint.name, "ba leave", 10)

		_columns, rows = ba_report(
			{"start_date": PERIOD[0], "end_date": PERIOD[1], "business_analyst": BA_USER}
		)
		row = self._row_for(
			rows, "business_analyst", frappe.db.get_value("User", BA_USER, "full_name")
		)
		self.assertIsNotNone(row, f"no row for {BA_USER} in {rows}")
		self.assertEqual(row["leave_days"], 1.0)
		self.assertEqual(row["expected_velocity"], 60.0)  # 100 × 3/5
