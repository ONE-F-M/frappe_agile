# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""The patch removes the Find PR On GitHub Server Script and is safe to run twice."""

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_agile.patches.v1 import delete_find_pr_on_github_script

SCRIPT_NAME = "Find PR On GitHub"


class TestDeleteFindPrOnGithubScript(FrappeTestCase):
	def test_the_script_is_deleted_and_a_second_run_does_nothing(self):
		if not frappe.db.exists("Server Script", SCRIPT_NAME):
			frappe.get_doc(
				{"doctype": "Server Script", "name": SCRIPT_NAME, "script_type": "API", "api_method": "find_pr_on_github_test", "script": "result = 1"}
			).insert(ignore_permissions=True)
		delete_find_pr_on_github_script.execute()
		self.assertFalse(frappe.db.exists("Server Script", SCRIPT_NAME))
		delete_find_pr_on_github_script.execute()
