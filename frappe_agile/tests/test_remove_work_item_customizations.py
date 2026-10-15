# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

"""The remove_work_item_customizations patch deletes every Custom Field and
Property Setter on Work Item, and leaves the DocType's own fields alone."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_agile.patches.v1.remove_work_item_customizations import execute

CUSTOM_FIELD_NAME = "Work Item-test_patch_custom_field"
PROPERTY_SETTER_NAME = "Work Item-description-label"


class TestRemoveWorkItemCustomizations(FrappeTestCase):
	def test_customizations_are_removed_and_doctype_fields_stay(self):
		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": "Work Item",
				"fieldname": "test_patch_custom_field",
				"fieldtype": "Data",
				"label": "Test Patch Custom Field",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Property Setter",
				"doctype_or_field": "DocField",
				"doc_type": "Work Item",
				"field_name": "description",
				"property": "label",
				"property_type": "Data",
				"value": "Test Patch Label",
			}
		).insert(ignore_permissions=True)

		self.assertTrue(frappe.db.exists("Custom Field", {"dt": "Work Item"}))
		self.assertTrue(frappe.db.exists("Property Setter", {"doc_type": "Work Item"}))

		execute()

		self.assertFalse(frappe.db.exists("Custom Field", CUSTOM_FIELD_NAME))
		self.assertFalse(frappe.db.exists("Property Setter", PROPERTY_SETTER_NAME))
		self.assertEqual(frappe.get_all("Custom Field", filters={"dt": "Work Item"}), [])
		self.assertEqual(frappe.get_all("Property Setter", filters={"doc_type": "Work Item"}), [])
		self.assertIsNotNone(frappe.get_meta("Work Item").get_field("workflow_state"))

	def test_running_again_with_nothing_to_remove_does_nothing(self):
		execute()
		execute()
		self.assertEqual(frappe.get_all("Custom Field", filters={"dt": "Work Item"}), [])
