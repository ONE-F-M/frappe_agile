# Copyright (c) 2026, One FM and Contributors
# See license.txt

import os

# import frappe
from frappe.tests.utils import FrappeTestCase


class TestFrappeAgileSettings(FrappeTestCase):
	def test_form_script_sets_intro(self):
		path = os.path.join(os.path.dirname(__file__), "frappe_agile_settings.js")
		with open(path) as f:
			source = f.read()

		self.assertIn("frm.set_intro(", source)
		self.assertIn("Settings for Frappe Agile work items and sprints.", source)
		# the intro must be set inside the refresh handler, before the sync button
		self.assertLess(source.index("frm.set_intro("), source.index("frm.add_custom_button("))
