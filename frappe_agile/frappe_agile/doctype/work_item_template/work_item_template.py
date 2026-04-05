# Copyright (c) 2026, Frappe Agile and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WorkItemTemplate(Document):
	def validate(self):
		self.ensure_single_default()

	def ensure_single_default(self):
		if self.default_template:
			# Uncheck all other default templates
			frappe.db.set_value(
				"Work Item Template",
				{"name": ["!=", self.name], "default_template": 1},
				"default_template",
				0
			)

	def on_trash(self):
		if frappe.db.exists("Work Item", {"work_item_template": self.name}):
			frappe.throw(
				frappe._("Cannot delete Work Item Template because it is linked to one or more Work Items."),
				title=frappe._("Cannot Delete")
			)
