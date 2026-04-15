# Copyright (c) 2026, One FM and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestLabel(FrappeTestCase):
	def test_create_label(self):
		"""Label can be created and its name equals the label value."""
		label = frappe.get_doc({"doctype": "Label", "label": "Gemini"})
		label.insert(ignore_permissions=True)

		self.assertTrue(frappe.db.exists("Label", "Gemini"))
		self.assertEqual(label.name, "Gemini")

	def test_labels_on_work_item(self):
		"""Multiple Labels can be attached to a Work Item and persist after reload."""
		# Create two Label records
		for label_name in ("Copilot", "Cursor"):
			if not frappe.db.exists("Label", label_name):
				frappe.get_doc({"doctype": "Label", "label": label_name}).insert(
					ignore_permissions=True
				)

		# Create a Work Item with labels attached
		work_item = frappe.get_doc(
			{
				"doctype": "Work Item",
				"title": "Test Label Attachment",
				"work_item_type": "Task",
				"labels": [
					{"label": "Copilot"},
					{"label": "Cursor"},
				],
			}
		)
		work_item.insert(ignore_permissions=True)

		# Reload and verify round-trip persistence
		reloaded = frappe.get_doc("Work Item", work_item.name)
		self.assertEqual(len(reloaded.labels), 2)

		attached_labels = sorted([d.label for d in reloaded.labels])
		self.assertEqual(attached_labels, ["Copilot", "Cursor"])
