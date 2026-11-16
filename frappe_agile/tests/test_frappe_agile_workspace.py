# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.tests.utils import FrappeTestCase


class TestFrappeAgileWorkspace(FrappeTestCase):
	def test_the_workspace_is_open_to_the_agile_roles(self):
		path = frappe.get_app_path(
			"frappe_agile", "frappe_agile", "workspace", "frappe_agile", "frappe_agile.json"
		)
		with open(path) as f:
			roles = {row["role"] for row in json.load(f)["roles"]}
		self.assertEqual(roles, {"System Manager", "Process Owner", "Business Analyst", "Developer"})
