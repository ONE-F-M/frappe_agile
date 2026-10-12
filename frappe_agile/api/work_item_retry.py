"""Retry from last commit: hand a Work Item the orchestrator gave up on back to the orchestrator."""

import frappe
from frappe import _
from SpiffWorkflow.util.task import TaskState

from one_bpmn.one_bpmn import engine

RETRY_WAIT = "Event_fb_retry_wait"


@frappe.whitelist()
def get_retry_state(work_item: str) -> dict:
	"""Whether the Work Item can be retried now, and if not, why."""
	frappe.has_permission("Work Item", "read", doc=work_item, throw=True)
	return {"reason": _reason_not_to_retry(work_item)}


@frappe.whitelist(methods=["POST"])
def retry_from_last_commit(work_item: str) -> dict:
	"""Assign the Work Item to the orchestrator again. Its process wakes on the edit and continues from the branch."""
	doc = frappe.get_doc("Work Item", work_item)
	doc.check_permission("write")
	if reason := _reason_not_to_retry(work_item):
		frappe.throw(reason)
	doc.orchestrator = 1
	doc.save()
	doc.add_comment(
		"Comment",
		"<b>Retry requested</b><br>" + frappe.utils.escape_html(frappe.session.user)
		+ " assigned this item to the orchestrator again. It continues from the branch's last commit.",
	)
	return {"ok": True}


def _reason_not_to_retry(work_item: str) -> str:
	"""'' when the item can be retried: with a person, no pull request yet, and its process waiting for this."""
	row = frappe.db.get_value("Work Item", work_item, ["orchestrator", "pr_link"], as_dict=True)
	if row.orchestrator:
		return _("This item is already assigned to the orchestrator.")
	if row.pr_link:
		return _("This item already has a pull request, so the review decides what happens next.")
	if not _waiting_for_retry(work_item):
		return _("This item's process is not waiting for it to be assigned to the orchestrator again.")
	return ""


def _waiting_for_retry(work_item: str) -> bool:
	for name in frappe.get_all(
		"BPMN Process Instance",
		filters={"context_doctype": "Work Item", "context_docname": work_item, "status": "Active"},
		pluck="name",
	):
		instance = frappe.get_doc("BPMN Process Instance", name)
		workflow = engine.restore_workflow(
			workflow_state=instance._load_json(instance.workflow_state),
			context_doctype=instance.context_doctype,
			context_docname=instance.context_docname,
			instance=instance,
		)
		if any(task.task_spec.name == RETRY_WAIT for task in workflow.get_tasks(state=TaskState.WAITING)):
			return True
	return False
