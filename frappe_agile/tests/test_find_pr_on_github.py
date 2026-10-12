# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""The fallback finds a PR by the Work Item's branch and says what the process does next."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_agile.frappe_agile.custom.server_script.server_script import get_server_script_json_file

REPO = "_test_find_pr"
SCRIPT = "Find PR On GitHub"
PULLS = "frappe.integrations.utils.make_get_request"


def _pull(state="open", merged_at=None, reviewers=(), updated_at="2026-10-08T10:00:00Z"):
	return {
		"updated_at": updated_at,
		"html_url": "https://github.com/ONE-F-M/_test_find_pr/pull/7",
		"title": "A change",
		"number": 7,
		"state": state,
		"merged_at": merged_at,
		"head": {"ref": "agent-branch"},
		"base": {"ref": "staging"},
		"user": {"login": "the-agent"},
		"requested_reviewers": [{"login": login} for login in reviewers],
	}


class TestFindPrOnGithub(FrappeTestCase):
	def setUp(self):
		if not (frappe.db.exists("DocType", "GitHub Repository") and frappe.db.get_value("Work Item", {}, "name")):
			self.skipTest("the site has no GitHub Repository or Work Item to work with")
		if not frappe.db.exists("GitHub Repository", REPO):
			frappe.get_doc(
				{"doctype": "GitHub Repository", "repo_name": REPO, "html_url": f"https://github.com/ONE-F-M/{REPO}"}
			).insert(ignore_permissions=True)
		source = frappe.get_doc("Work Item", frappe.db.get_value("Work Item", {}, "name"))
		doc = frappe.copy_doc(source)
		doc.title = f"_Test find pr {frappe.generate_hash(length=8)}"
		doc.orchestrator = 0
		doc.assignee_user = None
		doc.pr_link = None
		doc.target_app = REPO
		doc.insert(ignore_permissions=True)
		frappe.db.set_value("Work Item", doc.name, "orchestrator", 1)
		self.work_item = doc.name
		self.script = get_server_script_json_file("find_pr_on_github.json")["script"]

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _run(self, pulls=None, error=None, reviews=None, reviews_error=None, ahead=None, post_error=None, **task_data):
		scope = {
			"context_doctype": "Work Item",
			"context_docname": self.work_item,
			"task_data": task_data,
			"result": {},
		}

		def answer(url, **kwargs):
			if error:
				raise error
			if "/compare/" in url:
				if ahead is None:
					raise Exception("404 Not Found")
				return {"ahead_by": ahead}
			if "/reviews" in url:
				if reviews_error:
					raise reviews_error
				return reviews or []
			return pulls or []

		mock = patch(PULLS, side_effect=answer)

		def create(url, **kwargs):
			if post_error:
				raise post_error
			self.created = kwargs["json"]
			return _pull(state="open")

		self.created = None
		post = patch("frappe.integrations.utils.make_post_request", side_effect=create)
		# The engine runs trusted Server Scripts with plain exec and the real frappe module.
		namespace = {"frappe": frappe, "__builtins__": __builtins__, **scope}
		with mock as pulls_mock, post, patch("frappe.enqueue") as enqueue:
			exec(self.script, namespace)
		self.pulls_mock, self.enqueue = pulls_mock, enqueue
		return scope["result"]

	def _sandbox_run(self, state):
		frappe.get_doc(
			{
				"doctype": "Agent Sandbox Run",
				"state": state,
				"request_payload": json.dumps({"work_item_id": self.work_item, "action": "run_tests"}),
			}
		).insert(ignore_permissions=True)

	def test_the_script_passes_the_engines_permission_screen(self):
		from one_bpmn.one_bpmn.engine import _check_script_permissions

		_check_script_permissions(self.script, SCRIPT)

	def test_an_open_pull_request_is_found_with_the_webhook_keys(self):
		result = self._run(pulls=[_pull(reviewers=["reviewer-one"])])

		self.assertEqual(result["fallback_outcome"], "pr_found")
		self.assertEqual(result["pr_url"], "https://github.com/ONE-F-M/_test_find_pr/pull/7")
		self.assertEqual(result["reviewer_github_login"], "reviewer-one")
		self.assertEqual(result["branch"], "agent-branch")
		self.assertEqual(result["action"], "opened")

	def test_a_closed_unmerged_pull_request_does_not_count(self):
		result = self._run(pulls=[_pull(state="closed")])
		self.assertEqual(result["fallback_outcome"], "no_pr")

	def test_a_merged_pull_request_counts(self):
		result = self._run(pulls=[_pull(state="closed", merged_at="2026-10-08T10:00:00Z")])
		self.assertEqual(result["fallback_outcome"], "pr_found")
		self.assertEqual(result["pr_state"], "merged")

	def test_no_pull_request_and_nothing_running_counts_a_failed_attempt(self):
		result = self._run(orch_attempt=1)

		self.assertEqual(result["fallback_outcome"], "no_pr")
		self.assertEqual(result["orch_attempt"], 2)
		self.assertIn("attempt 2 of 3", result["fallback_reason"])

	def test_the_third_failed_attempt_is_exhausted(self):
		result = self._run(orch_attempt=2)
		self.assertEqual(result["fallback_outcome"], "exhausted")
		self.assertEqual(result["orch_attempt"], 3)

	def test_a_running_sandbox_keeps_the_wait_and_counts_no_attempt(self):
		self._sandbox_run("running")

		result = self._run(orch_attempt=1, fallback_checks=4)

		self.assertEqual(result["fallback_outcome"], "sandbox_running")
		self.assertEqual(result["orch_attempt"], 1)
		self.assertEqual(result["fallback_checks"], 5)

	def test_a_finished_sandbox_run_does_not_hold_the_wait(self):
		self._sandbox_run("completed")
		self.assertEqual(self._run()["fallback_outcome"], "no_pr")

	def test_a_run_stuck_running_stops_holding_the_wait_at_the_cap(self):
		self._sandbox_run("running")

		result = self._run(orch_attempt=0, fallback_checks=59)

		self.assertEqual(result["fallback_outcome"], "no_pr")
		self.assertEqual(result["orch_attempt"], 1)
		self.assertEqual(result["fallback_checks"], 0)

	def test_a_github_error_keeps_the_wait_without_counting_an_attempt(self):
		result = self._run(error=Exception("rate limited"), orch_attempt=1)

		self.assertEqual(result["fallback_outcome"], "github_error")
		self.assertIn("rate limited", result["fallback_error"])
		self.assertEqual(result["orch_attempt"], 1)

	def test_a_pull_request_not_updated_since_the_rerun_began_does_not_count(self):
		since = 1791456000.0  # 2026-10-08 10:40:00 UTC
		result = self._run(pulls=[_pull(updated_at="2026-10-08T10:00:00Z")], fallback_since=since)
		self.assertEqual(result["fallback_outcome"], "no_pr")

	def test_a_pull_request_updated_after_the_rerun_began_counts(self):
		since = 1791456000.0
		result = self._run(pulls=[_pull(updated_at="2026-10-08T11:00:00Z")], fallback_since=since)
		self.assertEqual(result["fallback_outcome"], "pr_found")

	def test_the_reason_is_set_for_the_hand_back_script(self):
		result = self._run(orch_attempt=2)
		self.assertEqual(result["reason"], result["fallback_reason"])
		self.assertEqual(result["reviewer_github_login"], "")

	def _events(self):
		return self.enqueue.call_args.kwargs["events"]

	def test_a_pull_request_the_process_never_heard_about_is_replayed_in_order(self):
		result = self._run(pulls=[_pull(reviewers=["reviewer-one"])])

		self.enqueue.assert_called_once()
		self.assertEqual(self.enqueue.call_args.args[0], "frappe_agile.api.github_webhook.replay_events")
		self.assertTrue(self.enqueue.call_args.kwargs["enqueue_after_commit"])
		self.assertEqual(self.enqueue.call_args.kwargs["work_item"], self.work_item)
		self.assertEqual([name for name, _ in self._events()], ["github:pull_request:opened", "github:pull_request:review_requested"])
		self.assertEqual(self._events()[1][1]["action"], "review_requested")
		self.assertEqual(self._events()[1][1]["reviewer_github_login"], "reviewer-one")
		self.assertEqual(result["fallback_replayed"], 2)

	def test_a_pull_request_with_no_reviewer_replays_only_opened(self):
		self._run(pulls=[_pull()])
		self.assertEqual([name for name, _ in self._events()], ["github:pull_request:opened"])

	def test_an_unanswered_change_request_is_replayed_after_the_review_request(self):
		reviews = [{"state": "CHANGES_REQUESTED", "user": {"login": "alice"}}]

		self._run(pulls=[_pull(reviewers=("alice",))], reviews=reviews)

		events = self.enqueue.call_args.kwargs["events"]
		self.assertEqual(
			[name for name, _ in events],
			["github:pull_request:opened", "github:pull_request:review_requested", "github:pull_request_review:changes_requested"],
		)
		self.assertEqual(events[2][1]["review_state"], "changes_requested")
		self.assertEqual(events[2][1]["reviewer_github_login"], "alice")

	def test_a_change_request_the_reviewer_later_approved_is_not_replayed(self):
		reviews = [
			{"state": "CHANGES_REQUESTED", "user": {"login": "alice"}},
			{"state": "COMMENTED", "user": {"login": "alice"}},
			{"state": "APPROVED", "user": {"login": "alice"}},
		]

		self._run(pulls=[_pull()], reviews=reviews)

		names = [name for name, _ in self.enqueue.call_args.kwargs["events"]]
		self.assertNotIn("github:pull_request_review:changes_requested", names)

	def test_a_change_request_on_a_rerun_is_not_replayed(self):
		reviews = [{"state": "CHANGES_REQUESTED", "user": {"login": "alice"}}]

		self._run(pulls=[_pull(updated_at="2099-01-01T00:00:00Z")], reviews=reviews, fallback_since=1791456000.0)

		self.enqueue.assert_not_called()

	def test_a_reviews_error_keeps_the_other_events_and_is_reported(self):
		result = self._run(pulls=[_pull(reviewers=("alice",))], reviews_error=Exception("down"))

		names = [name for name, _ in self.enqueue.call_args.kwargs["events"]]
		self.assertEqual(names, ["github:pull_request:opened", "github:pull_request:review_requested"])
		self.assertIn("reviews", result["fallback_error"])

	def _with_base_branch(self, branch="staging"):
		frappe.db.set_value("Work Item", self.work_item, "git_branch", branch)

	def test_a_branch_with_commits_and_no_pull_request_gets_one_opened(self):
		self._with_base_branch()
		result = self._run(pulls=[], ahead=3)
		self.assertEqual(result["fallback_outcome"], "pr_found")
		self.assertEqual(result["fallback_finalized"], 1)
		self.assertEqual((self.created["head"], self.created["base"]), (self.work_item, "staging"))
		self.assertFalse(self.created["draft"])
		names = [name for name, _ in self.enqueue.call_args.kwargs["events"]]
		self.assertEqual(names[0], "github:pull_request:opened")

	def test_the_opened_pull_request_carries_the_orchestrators_last_report(self):
		self._with_base_branch()
		frappe.get_doc({
			"doctype": "Comment", "comment_type": "Comment", "reference_doctype": "Work Item",
			"reference_name": self.work_item, "content": "<b>Orchestrator</b><br>Added the field and its test.",
		}).insert(ignore_permissions=True)
		self._run(pulls=[], ahead=1)
		self.assertIn("Added the field and its test.", self.created["body"])
		self.assertIn(self.work_item, self.created["body"])

	def test_a_failed_test_run_makes_the_opened_pull_request_a_draft(self):
		self._with_base_branch()
		self._sandbox_run("failed")
		frappe.db.set_value(
			"Agent Sandbox Run", frappe.get_all("Agent Sandbox Run", pluck="name", order_by="creation desc", limit=1)[0],
			{"work_item": self.work_item, "action": "run_tests"},
		)
		self._run(pulls=[], ahead=1)
		self.assertTrue(self.created["draft"])

	def test_a_branch_with_nothing_ahead_of_base_opens_nothing(self):
		self._with_base_branch()
		result = self._run(pulls=[], ahead=0)
		self.assertEqual(result["fallback_outcome"], "no_pr")
		self.assertIsNone(self.created)

	def test_a_branch_that_does_not_exist_on_github_opens_nothing(self):
		self._with_base_branch()
		result = self._run(pulls=[], ahead=None)
		self.assertEqual(result["fallback_outcome"], "no_pr")
		self.assertIsNone(self.created)

	def test_an_existing_closed_pull_request_is_not_replaced(self):
		self._with_base_branch()
		result = self._run(pulls=[_pull(state="closed")], ahead=2)
		self.assertEqual(result["fallback_outcome"], "no_pr")
		self.assertIsNone(self.created)

	def test_a_running_sandbox_is_given_time_before_a_pull_request_is_opened(self):
		self._with_base_branch()
		self._sandbox_run("running")
		result = self._run(pulls=[], ahead=2)
		self.assertEqual(result["fallback_outcome"], "sandbox_running")
		self.assertIsNone(self.created)

	def test_an_item_with_no_base_branch_opens_nothing(self):
		frappe.db.set_value("Work Item", self.work_item, "git_branch", None)
		self._run(pulls=[], ahead=2)
		self.assertIsNone(self.created)

	def test_a_refused_pull_request_is_reported_and_counts_as_no_pull_request(self):
		self._with_base_branch()
		result = self._run(pulls=[], ahead=2, post_error=Exception("403 Forbidden"))
		self.assertEqual(result["fallback_outcome"], "no_pr")
		self.assertIn("403", result["finalize_error"])

	def _attempt_comments(self):
		return frappe.get_all(
			"Comment", filters={"reference_doctype": "Work Item", "reference_name": self.work_item, "comment_type": "Comment"},
			pluck="content",
		)

	def test_a_new_attempt_is_announced_on_the_work_item_with_the_last_failure(self):
		failed = frappe.get_doc({
			"doctype": "Agent Sandbox Run", "state": "failed", "target_app": "one_bpmn", "work_item": self.work_item,
			"failure_class": "code", "error_message": "AssertionError: 2 != 3",
		}).insert(ignore_permissions=True)
		self.assertTrue(failed.name)
		self._run(orch_attempt=0)
		text = " ".join(self._attempt_comments())
		self.assertIn("Attempt 1 of 3", text)
		self.assertIn("Last sandbox failure (code)", text)
		self.assertIn("AssertionError", text)

	def test_a_new_attempt_with_no_failed_run_is_announced_without_a_failure_line(self):
		self._run(orch_attempt=0)
		text = " ".join(self._attempt_comments())
		self.assertIn("Attempt 1 of 3", text)
		self.assertNotIn("Last sandbox failure", text)

	def test_a_found_pull_request_and_the_final_hand_back_add_no_attempt_comment(self):
		self._run(pulls=[_pull()])
		self._run(orch_attempt=2)
		self.assertEqual([c for c in self._attempt_comments() if "Attempt" in c], [])

	def test_a_found_pull_request_gets_its_acceptance_criteria_published(self):
		with patch("one_bpmn.one_bpmn.connectors.agent_criteria.publish_criteria", return_value={"criteria_unmet": ["AC2"]}) as publish:
			result = self._run(pulls=[_pull()])
		publish.assert_called_once()
		self.assertEqual(publish.call_args.args[0], self.work_item)
		self.assertEqual(publish.call_args.args[1], "ONE-F-M/_test_find_pr")
		self.assertEqual(result["criteria_unmet"], ["AC2"])

	def test_a_publishing_failure_is_reported_and_does_not_lose_the_pull_request(self):
		with patch("one_bpmn.one_bpmn.connectors.agent_criteria.publish_criteria", side_effect=Exception("422 body too long")):
			result = self._run(pulls=[_pull()])
		self.assertEqual(result["fallback_outcome"], "pr_found")
		self.assertIn("422", result["criteria_error"])

	def test_no_pull_request_publishes_nothing(self):
		with patch("one_bpmn.one_bpmn.connectors.agent_criteria.publish_criteria") as publish:
			self._run(pulls=[])
		publish.assert_not_called()

	def _hand_back(self):
		frappe.db.set_value("Work Item", self.work_item, "orchestrator", 0)

	def test_an_item_handed_back_to_a_person_is_its_own_outcome_and_counts_no_attempt(self):
		self._hand_back()
		result = self._run(orch_attempt=0)
		self.assertEqual(result["fallback_outcome"], "handed_back")
		self.assertEqual(result["orch_attempt"], 0)
		self.assertIn("assigned to the orchestrator again", result["fallback_reason"])
		self.assertEqual([c for c in self._attempt_comments() if "Attempt" in c], [])

	def test_an_item_handed_back_with_commits_gets_a_draft_pull_request(self):
		self._hand_back()
		frappe.db.set_value("Work Item", self.work_item, "git_branch", "staging")
		result = self._run(pulls=[], ahead=3)
		self.assertEqual(result["fallback_outcome"], "pr_found")
		self.assertTrue(self.created["draft"])
		self.assertIn("handed the item back", self.created["body"])

	def test_an_item_handed_back_with_nothing_pushed_opens_nothing(self):
		self._hand_back()
		frappe.db.set_value("Work Item", self.work_item, "git_branch", "staging")
		result = self._run(pulls=[], ahead=0)
		self.assertEqual(result["fallback_outcome"], "handed_back")
		self.assertIsNone(self.created)

	def test_an_item_with_no_base_branch_uses_the_base_its_sandbox_runs_used(self):
		frappe.db.set_value("Work Item", self.work_item, "git_branch", None)
		frappe.get_doc(
			{"doctype": "Agent Sandbox Run", "state": "completed", "work_item": self.work_item, "git_branch": "staging"}
		).insert(ignore_permissions=True)
		self._run(pulls=[], ahead=2)
		self.assertEqual(self.created["base"], "staging")

	def test_an_item_handed_back_after_a_pull_request_exists_still_gets_it_recorded(self):
		self._hand_back()
		result = self._run(pulls=[_pull()])
		self.assertEqual(result["fallback_outcome"], "pr_found")

	def test_a_merged_pull_request_also_replays_the_merge(self):
		self._run(pulls=[_pull(state="closed", merged_at="2026-10-08T10:00:00Z")])
		self.assertEqual(
			[name for name, _ in self._events()], ["github:pull_request:opened", "github:pull_request:merged"]
		)

	def test_a_rerun_replays_nothing_because_the_pull_request_is_not_new(self):
		result = self._run(pulls=[_pull(updated_at="2026-10-08T11:00:00Z")], fallback_since=1791456000.0)

		self.assertEqual(result["fallback_outcome"], "pr_found")
		self.enqueue.assert_not_called()

	def test_an_item_with_its_pull_request_link_and_reviewer_asks_github_nothing(self):
		frappe.db.set_value(
			"Work Item",
			self.work_item,
			{"pr_link": "https://github.com/ONE-F-M/_test_find_pr/pull/9", "pr_reviewer_user": "Administrator"},
		)

		result = self._run(pulls=[_pull()])

		self.assertEqual(result["fallback_outcome"], "already_linked")
		self.pulls_mock.assert_not_called()
		self.enqueue.assert_not_called()
		self.assertEqual(result["orch_attempt"], 0)

	def test_a_linked_item_without_a_reviewer_replays_the_missed_review_request_only(self):
		frappe.db.set_value("Work Item", self.work_item, "pr_link", "https://github.com/ONE-F-M/_test_find_pr/pull/7")

		result = self._run(pulls=[_pull(reviewers=("alice",))])

		self.assertEqual(result["fallback_outcome"], "already_linked")
		events = self.enqueue.call_args.kwargs["events"]
		self.assertEqual([name for name, _ in events], ["github:pull_request:review_requested"])
		self.assertEqual(events[0][1]["reviewer_github_login"], "alice")

	def test_a_linked_item_without_a_reviewer_and_no_reviewer_on_github_replays_nothing(self):
		frappe.db.set_value("Work Item", self.work_item, "pr_link", "https://github.com/ONE-F-M/_test_find_pr/pull/7")

		result = self._run(pulls=[_pull()])

		self.assertEqual(result["fallback_outcome"], "already_linked")
		self.enqueue.assert_not_called()

	def test_a_linked_item_stays_linked_when_github_does_not_answer(self):
		frappe.db.set_value("Work Item", self.work_item, "pr_link", "https://github.com/ONE-F-M/_test_find_pr/pull/7")

		result = self._run(error=Exception("down"))

		self.assertEqual(result["fallback_outcome"], "already_linked")
		self.enqueue.assert_not_called()

	def test_a_rerun_still_looks_the_pull_request_up_when_the_link_is_set(self):
		frappe.db.set_value("Work Item", self.work_item, "pr_link", "https://github.com/ONE-F-M/_test_find_pr/pull/9")

		result = self._run(pulls=[_pull(updated_at="2026-10-08T10:00:00Z")], fallback_since=1791456000.0)

		self.assertEqual(result["fallback_outcome"], "no_pr")
		self.pulls_mock.assert_called_once()

	def test_no_pull_request_replays_nothing(self):
		self._run(orch_attempt=2)
		self.enqueue.assert_not_called()


class TestReplayEvents(FrappeTestCase):
	def test_events_are_delivered_to_the_work_item_in_order(self):
		from frappe_agile.api import github_webhook

		events = [["github:pull_request:opened", {"pr_url": "a"}], ["github:pull_request:review_requested", {"pr_url": "a"}]]
		with patch.object(github_webhook, "_deliver_bpmn_message") as deliver:
			github_webhook.replay_events("_test_work_item", events)

		self.assertEqual(
			[call.args for call in deliver.call_args_list],
			[("_test_work_item", name, payload) for name, payload in events],
		)
