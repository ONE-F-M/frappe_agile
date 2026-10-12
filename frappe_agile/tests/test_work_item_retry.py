# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""A handed-back Work Item can be assigned to the orchestrator again, and only when its process is waiting for that."""

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_agile.api import work_item_retry as retry
from one_bpmn.api.compilation import compile_process_model

MODEL = "WI Retry Api"
PROCESS_ID = "wi_retry_api_process"


def _map(event_id: str) -> str:
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
                  id="Defs_{PROCESS_ID}" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:message id="Msg_edit" name="WorkItem_Edit_Action" />
  <bpmn:process id="{PROCESS_ID}" isExecutable="true">
    <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="{event_id}" />
    <bpmn:intermediateCatchEvent id="{event_id}" name="Wait">
      <bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>
      <bpmn:messageEventDefinition messageRef="Msg_edit" />
    </bpmn:intermediateCatchEvent>
    <bpmn:sequenceFlow id="f2" sourceRef="{event_id}" targetRef="e" />
    <bpmn:endEvent id="e"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""


class TestWorkItemRetry(FrappeTestCase):
	def setUp(self):
		source = frappe.db.get_value("Work Item", {}, "name")
		if not source:
			self.skipTest("the site has no Work Item to copy")
		item = frappe.copy_doc(frappe.get_doc("Work Item", source))
		item.title = f"_Test retry api {frappe.generate_hash(length=8)}"
		item.orchestrator = 0
		item.assignee_user = None
		item.pr_link = None
		item.insert(ignore_permissions=True)
		self.work_item = item.name
		for started in frappe.get_all("BPMN Process Instance", filters={"context_docname": item.name}, pluck="name"):
			frappe.delete_doc("BPMN Process Instance", started, force=True, ignore_permissions=True)
		self.addCleanup(frappe.db.rollback)

	def _start(self, event_id=retry.RETRY_WAIT):
		if frappe.db.exists("BPMN Process Model", MODEL):
			frappe.delete_doc("BPMN Process Model", MODEL, force=1, ignore_permissions=True)
		model = frappe.new_doc("BPMN Process Model")
		model.name, model.title, model.process_id, model.bpmn_xml, model.version = MODEL, MODEL, PROCESS_ID, _map(event_id), 1
		model.insert(ignore_permissions=True)
		compile_process_model(MODEL)
		instance = frappe.new_doc("BPMN Process Instance")
		instance.process_model = MODEL
		instance.context_doctype = "Work Item"
		instance.context_docname = self.work_item
		instance.insert(ignore_permissions=True)
		instance.start()
		return instance

	def _fresh_request(self):
		frappe.flags._bpmn_message_sent = set()
		frappe.flags._bpmn_instances_just_started = set()

	def test_an_item_with_a_person_and_a_waiting_process_can_be_retried(self):
		self._start()
		self.assertEqual(retry.get_retry_state(self.work_item), {"reason": ""})

	def test_an_item_already_with_the_orchestrator_cannot(self):
		self._start()
		frappe.db.set_value("Work Item", self.work_item, "orchestrator", 1)
		self.assertIn("already assigned to the orchestrator", retry.get_retry_state(self.work_item)["reason"])

	def test_an_item_with_a_pull_request_cannot(self):
		self._start()
		frappe.db.set_value("Work Item", self.work_item, "pr_link", "https://github.com/o/r/pull/1")
		self.assertIn("already has a pull request", retry.get_retry_state(self.work_item)["reason"])

	def test_an_item_whose_process_is_not_at_the_retry_wait_cannot(self):
		self._start(event_id="Event_somewhere_else")
		self.assertIn("not waiting", retry.get_retry_state(self.work_item)["reason"])

	def test_an_item_with_no_running_process_cannot(self):
		self.assertIn("not waiting", retry.get_retry_state(self.work_item)["reason"])

	def test_a_finished_process_does_not_count(self):
		instance = self._start()
		instance.db_set("status", "Completed")
		self.assertIn("not waiting", retry.get_retry_state(self.work_item)["reason"])

	def test_retrying_assigns_it_to_the_orchestrator_comments_and_wakes_the_process(self):
		instance = self._start()
		self._fresh_request()
		self.assertEqual(retry.retry_from_last_commit(self.work_item), {"ok": True})
		row = frappe.db.get_value("Work Item", self.work_item, ["orchestrator", "assignee_user"], as_dict=True)
		self.assertEqual((row.orchestrator, row.assignee_user), (1, None))
		comments = frappe.get_all("Comment", filters={"reference_doctype": "Work Item", "reference_name": self.work_item}, pluck="content")
		self.assertTrue(any("Retry requested" in c for c in comments))
		instance.reload()
		self.assertEqual(instance.status, "Completed")

	def test_a_second_retry_is_refused(self):
		self._start()
		self._fresh_request()
		retry.retry_from_last_commit(self.work_item)
		with self.assertRaises(frappe.ValidationError):
			retry.retry_from_last_commit(self.work_item)

	def test_an_item_that_cannot_be_retried_is_refused_and_unchanged(self):
		with self.assertRaises(frappe.ValidationError):
			retry.retry_from_last_commit(self.work_item)
		self.assertFalse(frappe.db.get_value("Work Item", self.work_item, "orchestrator"))

	def test_a_user_who_cannot_read_the_item_is_refused(self):
		self._start()
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			retry.get_retry_state(self.work_item)
		with self.assertRaises(frappe.PermissionError):
			retry.retry_from_last_commit(self.work_item)
