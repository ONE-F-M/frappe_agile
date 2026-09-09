# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TechnicalResearch(Document):
	def on_submit(self):
		if self.create_work_items != "Yes":
			return

		for row in self.get("work_item") or []:
			work_item = frappe.new_doc("Work Item")
			work_item.work_item_type = row.work_item_type
			work_item.title = row.title
			work_item.description = row.description
			work_item.assignee_user = self.assignee
			work_item.insert()
