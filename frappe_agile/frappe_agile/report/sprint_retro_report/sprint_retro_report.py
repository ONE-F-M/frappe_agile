# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from frappe_agile.frappe_agile.report.proration import as_list

RETRO_FIELDS = [
	("delivery_rating", 130),
	("requirements_rating", 130),
	("communication_rating", 130),
	("next_sprint_rating", 130),
	("workload", 130),
	("answer_speed", 130),
	("meetings", 130),
	("timezone_impact", 130),
	("blocked_by", 150),
	("blocker_details", 220),
	("went_well", 250),
	("did_not_go_well", 250),
	("change_next_sprint", 250),
	("kudos", 220),
]


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	columns = [
		{"fieldname": "name", "label": _("Retro"), "fieldtype": "Link", "options": "Sprint Retro", "width": 140},
		{"fieldname": "submitted_by_name", "label": _("Submitted By"), "fieldtype": "Data", "width": 180},
		{"fieldname": "from_date", "label": _("From Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "to_date", "label": _("To Date"), "fieldtype": "Date", "width": 110},
	]
	meta = frappe.get_meta("Sprint Retro")
	columns += [
		{
			"fieldname": fieldname,
			"label": _(meta.get_label(fieldname)),
			"fieldtype": meta.get_field(fieldname).fieldtype,
			"width": width,
		}
		for fieldname, width in RETRO_FIELDS
	]
	return columns


def get_data(filters):
	retro_filters = {
		"docstatus": 1,
		"from_date": ("<=", filters.get("to_date")),
		"to_date": (">=", filters.get("from_date")),
	}
	submitted_by = as_list(filters.get("submitted_by"))
	if submitted_by:
		retro_filters["submitted_by"] = ("in", submitted_by)

	retros = frappe.get_list(
		"Sprint Retro",
		filters=retro_filters,
		fields=["name", "submitted_by", "from_date", "to_date"] + [f[0] for f in RETRO_FIELDS],
		order_by="from_date desc, submitted_by asc",
	)
	if not retros:
		return []

	full_names = dict(
		frappe.get_all(
			"User",
			filters={"name": ("in", list({r.submitted_by for r in retros}))},
			fields=["name", "full_name"],
			as_list=True,
		)
	)

	for retro in retros:
		retro.submitted_by_name = full_names.get(retro.submitted_by) or retro.submitted_by
	return retros


@frappe.whitelist()
def submitted_by_options(txt: str | None = None) -> list[dict]:
	"""Users with a submitted retro, by name, for the Submitted By filter."""
	frappe.has_permission("Sprint Retro", "read", throw=True)

	users = frappe.get_list("Sprint Retro", filters={"docstatus": 1}, pluck="submitted_by", distinct=True)
	if not users:
		return []

	filters = {"name": ("in", users)}
	if txt:
		filters["full_name"] = ("like", f"%{txt}%")

	return [
		{"value": u.name, "description": u.full_name or u.name}
		for u in frappe.get_all("User", filters=filters, fields=["name", "full_name"], order_by="full_name asc")
	]
