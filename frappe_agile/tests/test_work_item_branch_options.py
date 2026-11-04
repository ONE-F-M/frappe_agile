# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""The Work Item Branch field offers every branch an orchestrator can start from."""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestWorkItemBranchOptions(FrappeTestCase):
	def test_branch_offers_all_target_branches(self):
		options = frappe.get_meta("Work Item").get_field("git_branch").options.split("\n")
		self.assertEqual(
			options,
			["", "staging", "test-production", "version-15", "version-16", "processa-refactor"],
		)
