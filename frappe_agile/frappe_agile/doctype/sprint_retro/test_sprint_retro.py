# Copyright (c) 2026, One FM and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days

from frappe_agile.frappe_agile.doctype.sprint_retro.sprint_retro import get_last_wednesday
from frappe_agile.frappe_agile.report.sprint_retro_report import sprint_retro_report as report

START = "2031-01-06"
END = "2031-01-12"


class TestSprintRetro(FrappeTestCase):
	def tearDown(self):
		frappe.db.delete("Sprint Retro", {"submitted_by": frappe.session.user, "from_date": (">=", START)})

	def test_submitted_by_defaults_to_session_user(self):
		retro = make_retro().insert()
		self.assertEqual(retro.submitted_by, frappe.session.user)

	def test_last_wednesday(self):
		self.assertEqual(str(get_last_wednesday("2026-09-29")), "2026-09-23")
		self.assertEqual(str(get_last_wednesday("2026-09-23")), "2026-09-16")

	def test_from_date_defaults_to_last_wednesday(self):
		retro = make_retro(from_date=None).insert()
		self.assertEqual(str(retro.from_date), "2031-01-08")

	def test_to_date_before_from_date_is_blocked(self):
		self.assertRaises(frappe.ValidationError, make_retro(END, START).insert)

	def test_overlapping_retro_is_blocked(self):
		make_retro().insert()
		self.assertRaises(frappe.ValidationError, make_retro(add_days(START, 3), END).insert)

	def test_new_retro_allowed_after_cancel(self):
		retro = make_retro().insert()
		retro.submit()
		retro.cancel()
		make_retro().insert()

	def test_report_lists_submitted_retros_only(self):
		submitted = make_retro().insert()
		submitted.submit()
		make_retro(add_days(END, 1), add_days(END, 7)).insert()
		users = frappe.as_json([frappe.session.user])
		_, data = report.execute({"from_date": START, "to_date": add_days(END, 7), "submitted_by": users})
		self.assertEqual([row.name for row in data], [submitted.name])
		self.assertIn(frappe.session.user, [d["value"] for d in report.submitted_by_options()])

	def test_report_headers_match_doctype_labels(self):
		labels = {c["fieldname"]: c["label"] for c in report.get_columns()}
		self.assertEqual(labels["kudos"], frappe.get_meta("Sprint Retro").get_label("kudos"))

	def test_submitted_by_options_needs_read_permission(self):
		with self.set_user("Guest"):
			self.assertRaises(frappe.PermissionError, report.submitted_by_options)


def make_retro(from_date=START, to_date=END):
	return frappe.get_doc(
		{
			"doctype": "Sprint Retro",
			"from_date": from_date,
			"to_date": to_date,
			"delivery_rating": 0.8,
			"requirements_rating": 0.6,
			"communication_rating": 0.8,
			"next_sprint_rating": 1,
			"workload": "About right",
			"answer_speed": "Same day",
			"meetings": "About right",
			"timezone_impact": "No",
			"blocked_by": "Nothing",
			"went_well": "Shipped on time",
			"did_not_go_well": "Late review",
			"change_next_sprint": "Review daily",
		}
	)
