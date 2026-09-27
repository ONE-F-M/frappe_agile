# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate

WEDNESDAY = 2


class SprintRetro(Document):
	def validate(self):
		if not self.from_date:
			self.from_date = get_last_wednesday(self.to_date)
		self.validate_dates()
		self.validate_overlap()

	def validate_dates(self):
		if getdate(self.to_date) < getdate(self.from_date):
			frappe.throw(_("To Date cannot be before From Date."), title=_("Invalid Dates"))

	def validate_overlap(self):
		existing = frappe.db.exists(
			"Sprint Retro",
			{
				"submitted_by": self.submitted_by,
				"docstatus": ("<", 2),
				"name": ("!=", self.name),
				"from_date": ("<=", self.to_date),
				"to_date": (">=", self.from_date),
			},
		)
		if existing:
			frappe.throw(
				_("Retro {0} already covers some of these dates.").format(existing),
				title=_("Retro Already Exists"),
			)


def get_last_wednesday(date):
	"""The Wednesday before the date; a Wednesday gives the one a week earlier."""
	return add_days(date, -((getdate(date).weekday() - WEDNESDAY) % 7 or 7))
