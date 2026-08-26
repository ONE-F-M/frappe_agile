# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

"""Working-day proration shared by the two sprint performance reports.

A velocity target (points per sprint) is earned over the days a person would
normally be at work, so that is what the target is measured against:

    working_days = sprint calendar days - the person's weekly offs
    factor       = (working_days - holiday_days - leave_days) / working_days
    target       = velocity * factor

`holiday_days` are the entries on the employee's Holiday List that are *not*
flagged as a weekly off - public holidays. Weekly offs themselves never reduce
the target; they are already outside `working_days`.

No day is charged twice. Leave falling on a holiday costs one day, counted as a
holiday, whatever the Leave Type's "Include holidays within leaves as leaves"
setting says.

Where the calendar cannot be determined - no linked Employee, no Holiday List,
or HRMS not installed - the target is left alone.
"""

import frappe
from frappe.utils import cint, date_diff, flt, getdate

# Multiplier applied when the target should not be prorated at all.
NO_PRORATION = 1.0


def get_employee_map(users):
	"""Map each User to their linked Employee record.

	Where a User is linked to more than one Employee, an Active record is preferred.
	"""
	if not users:
		return {}

	employees = frappe.get_all(
		"Employee",
		filters={"user_id": ["in", list(users)]},
		fields=["name", "user_id", "status"],
	)

	emp_map = {}
	for emp in employees:
		if emp.user_id not in emp_map or emp.status == "Active":
			emp_map[emp.user_id] = emp.name
	return emp_map


def get_proration(employee, periods):
	"""Aggregate the working-day breakdown across several sprint periods.

	`periods` is an iterable of (start_date, end_date) pairs, one per distinct
	sprint period the person worked.

	Returns (factor, working_days, holiday_days, leave_days), where `factor` is
	what the velocity is multiplied by: one whole sprint per period, less the
	days lost within each.
	"""
	factor = 0.0
	working_days = 0
	holiday_days = 0
	leave_days = 0.0

	for start_date, end_date in periods:
		period = get_period_breakdown(employee, start_date, end_date)
		working_days += period["working_days"]
		holiday_days += period["holiday_days"]
		leave_days += period["leave_days"]
		factor += period["factor"]

	return factor, working_days, holiday_days, flt(leave_days, 2)


def get_period_breakdown(employee, start_date, end_date):
	"""Working days, days lost, and the resulting multiplier for one sprint period."""
	if not (start_date and end_date):
		return _breakdown(0, 0, 0.0, NO_PRORATION)

	start_date = getdate(start_date)
	end_date = getdate(end_date)

	calendar_days = date_diff(end_date, start_date) + 1
	if calendar_days <= 0:
		return _breakdown(0, 0, 0.0, NO_PRORATION)

	if not employee:
		# No staff record to look a calendar up against, so every calendar day
		# counts as a working day and the target stands as it is.
		return _breakdown(calendar_days, 0, 0.0, NO_PRORATION)

	holiday_list = _get_holiday_list(employee)
	weekly_offs, holiday_days = _split_holidays(holiday_list, start_date, end_date)

	working_days = calendar_days - weekly_offs
	if working_days <= 0:
		# The whole period is weekly offs - there is nothing to prorate against.
		return _breakdown(0, 0, 0.0, NO_PRORATION)

	holiday_days = min(holiday_days, working_days)
	leave_days = min(
		_get_leave_days(employee, holiday_list, start_date, end_date),
		working_days - holiday_days,
	)

	factor = (working_days - holiday_days - leave_days) / working_days
	return _breakdown(working_days, holiday_days, leave_days, factor)


def _breakdown(working_days, holiday_days, leave_days, factor):
	return {
		"working_days": working_days,
		"holiday_days": holiday_days,
		"leave_days": flt(leave_days, 2),
		"factor": factor,
	}


def _get_holiday_list(employee):
	"""The Holiday List that applies to the employee, or None if there isn't one."""
	try:
		from hrms.hr.utils import get_holiday_list_for_employee
	except ImportError:
		return None

	return get_holiday_list_for_employee(employee, raise_exception=False)


def _split_holidays(holiday_list, start_date, end_date):
	"""Count (weekly offs, public holidays) in the window, by distinct date.

	A date listed both ways counts as a weekly off: it is a non-working day
	either way, so it must not also cut the target.
	"""
	if not holiday_list:
		return 0, 0

	rows = frappe.get_all(
		"Holiday",
		filters={
			"parent": holiday_list,
			"holiday_date": ["between", [start_date, end_date]],
		},
		fields=["holiday_date", "weekly_off"],
	)

	weekly_offs = {row.holiday_date for row in rows if cint(row.weekly_off)}
	public = {row.holiday_date for row in rows if not cint(row.weekly_off)} - weekly_offs
	return len(weekly_offs), len(public)


def _holiday_count(holiday_list, start_date, end_date):
	"""Distinct holidays of any kind in the window."""
	weekly_offs, public = _split_holidays(holiday_list, start_date, end_date)
	return weekly_offs + public


def _get_leave_days(employee, holiday_list, start_date, end_date):
	"""Working days the employee's approved leave costs inside the window."""
	leave_apps = frappe.get_all(
		"Leave Application",
		filters={
			"employee": employee,
			"status": "Approved",
			"docstatus": 1,
			"from_date": ["<=", end_date],
			"to_date": [">=", start_date],
		},
		fields=["leave_type", "from_date", "to_date", "half_day", "half_day_date"],
	)

	leave_days = 0.0
	for la in leave_apps:
		# Clamp each leave application to the sprint window before counting
		clamped_from = max(getdate(la.from_date), start_date)
		clamped_to = min(getdate(la.to_date), end_date)
		if clamped_to < clamped_from:
			continue
		leave_days += _leave_days_for_application(
			employee, la, holiday_list, clamped_from, clamped_to
		)

	return leave_days


def _leave_days_for_application(employee, la, holiday_list, start_date, end_date):
	"""Working days one leave application costs, holidays excluded either way."""
	days = flt(_raw_leave_days(employee, la, holiday_list, start_date, end_date))

	if holiday_list and cint(frappe.db.get_value("Leave Type", la.leave_type, "include_holiday")):
		# This Leave Type counts holidays as leave; the report counts them as
		# holidays, so take them back out rather than charge the day twice.
		days -= _holiday_count(holiday_list, start_date, end_date)

	return max(days, 0.0)


def _raw_leave_days(employee, la, holiday_list, start_date, end_date):
	"""Leave days as HRMS counts them, falling back to a plain day count."""
	if holiday_list:
		try:
			from hrms.hr.doctype.leave_application.leave_application import (
				get_number_of_leave_days,
			)
		except ImportError:
			pass
		else:
			return get_number_of_leave_days(
				employee,
				la.leave_type,
				start_date,
				end_date,
				la.half_day,
				la.half_day_date,
				holiday_list=holiday_list,
			)

	# No calendar to exclude anything against - count the days themselves,
	# mirroring how HRMS handles a half day.
	days = date_diff(end_date, start_date) + 1
	half_day_date = getdate(la.half_day_date) if la.half_day_date else None
	if cint(la.half_day) and (
		start_date == end_date
		or (half_day_date and start_date <= half_day_date <= end_date)
	):
		days -= 0.5
	return days
