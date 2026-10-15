# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""
Unit tests for frappe_agile.api.github_webhook

Run with:
	bench --site onefm run-tests --app frappe_agile \
		--module frappe_agile.api.test_github_webhook
"""

import hashlib
import hmac
import json
import sys
import unittest
from unittest.mock import ANY, MagicMock, patch

import frappe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signature(secret: str, body: bytes) -> str:
	sig = hmac.new(
		key=secret.encode("utf-8"),
		msg=body,
		digestmod=hashlib.sha256,
	).hexdigest()
	return f"sha256={sig}"


def _build_pr_payload(
	action: str,
	merged: bool = False,
	body: str = "",
	title: str = "",
	branch: str = "feature/some-branch",
	pr_url: str = "https://github.com/org/repo/pull/1",
	requested_reviewers: list[dict] | None = None,
) -> dict:
	return {
		"action": action,
		"pull_request": {
			"html_url": pr_url,
			"merged": merged,
			"body": body,
			"title": title,
			"head": {"ref": branch},
			"requested_reviewers": requested_reviewers or [],
		},
	}


def _build_review_payload(
	state: str,
	body: str = "",
	title: str = "",
	branch: str = "feature/some-branch",
) -> dict:
	return {
		"review": {"state": state},
		"pull_request": {
			"html_url": "https://github.com/org/repo/pull/2",
			"body": body,
			"title": title,
			"head": {"ref": branch},
		},
	}


def _build_push_payload(
	ref: str = "refs/heads/feature/WI-000001-my-task",
	commit_messages: list[str] | None = None,
) -> dict:
	return {
		"ref": ref,
		"commits": [{"message": m} for m in (commit_messages or [])],
	}


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestGetWebhookSecret(unittest.TestCase):
	"""Tests for _get_webhook_secret() lookup priority."""

	def _mod(self):
		from frappe_agile.api import github_webhook
		return github_webhook

	@patch("frappe.conf")
	@patch("frappe_agile.api.github_webhook.get_decrypted_password", return_value="settings-secret")
	def test_settings_secret_takes_priority(self, _mock_decrypt, _mock_conf):
		"""When both Settings and conf have a secret, Settings wins."""
		_mock_conf.get.return_value = "conf-secret"
		result = self._mod()._get_webhook_secret()
		self.assertEqual(result, "settings-secret")

	@patch("frappe.conf")
	@patch("frappe_agile.api.github_webhook.get_decrypted_password", return_value="settings-secret")
	def test_settings_secret_only(self, _mock_decrypt, _mock_conf):
		"""When only Settings has a secret, it should be returned."""
		_mock_conf.get.return_value = None
		result = self._mod()._get_webhook_secret()
		self.assertEqual(result, "settings-secret")

	@patch("frappe.conf")
	@patch("frappe_agile.api.github_webhook.get_decrypted_password", return_value=None)
	def test_conf_fallback(self, _mock_decrypt, _mock_conf):
		"""When Settings is empty, should fall back to frappe.conf."""
		_mock_conf.get.return_value = "conf-secret"
		result = self._mod()._get_webhook_secret()
		self.assertEqual(result, "conf-secret")

	@patch("frappe.conf")
	@patch("frappe_agile.api.github_webhook.get_decrypted_password", return_value=None)
	def test_returns_none_when_not_configured(self, _mock_decrypt, _mock_conf):
		"""When neither source has a secret, return None."""
		_mock_conf.get.return_value = None
		result = self._mod()._get_webhook_secret()
		self.assertIsNone(result)


class TestGithubWebhookSignature(unittest.TestCase):
	"""HMAC signature verification tests."""

	def _mod(self):
		from frappe_agile.api import github_webhook
		return github_webhook

	def test_valid_signature_passes(self):
		"""A correctly-signed payload should not raise."""
		mod = self._mod()
		payload_bytes = b'{"action":"ping"}'
		sig = _make_signature("test-secret", payload_bytes)

		mock_request = MagicMock()
		mock_request.headers = {"X-Hub-Signature-256": sig}
		mock_request.data = payload_bytes

		with patch("frappe.request", mock_request):
			with patch("frappe_agile.api.github_webhook._get_webhook_secret", return_value="test-secret"):
				# Should not raise
				mod._verify_signature({})

	def test_missing_signature_raises(self):
		"""Missing header should raise AuthenticationError."""
		mod = self._mod()
		mock_request = MagicMock()
		mock_request.headers = {}
		mock_request.data = b"{}"

		with patch("frappe.request", mock_request):
			with patch("frappe_agile.api.github_webhook._get_webhook_secret", return_value="test-secret"):
				with self.assertRaises(frappe.exceptions.AuthenticationError):
					mod._verify_signature({})

	def test_wrong_signature_raises(self):
		"""A tampered payload should raise AuthenticationError."""
		mod = self._mod()
		payload_bytes = b'{"action":"ping"}'
		bad_sig = "sha256=deadbeef"

		mock_request = MagicMock()
		mock_request.headers = {"X-Hub-Signature-256": bad_sig}
		mock_request.data = payload_bytes

		with patch("frappe.request", mock_request):
			with patch("frappe_agile.api.github_webhook._get_webhook_secret", return_value="test-secret"):
				with self.assertRaises(frappe.exceptions.AuthenticationError):
					mod._verify_signature({})

	def test_no_secret_configured_raises(self):
		"""When no secret is configured anywhere, should raise AuthenticationError."""
		mod = self._mod()
		mock_request = MagicMock()
		mock_request.headers = {"X-Hub-Signature-256": "sha256=abc"}
		mock_request.data = b"{}"

		with patch("frappe.request", mock_request):
			with patch("frappe_agile.api.github_webhook._get_webhook_secret", return_value=None):
				with self.assertRaises(frappe.exceptions.AuthenticationError):
					mod._verify_signature({})


class TestExtractWiName(unittest.TestCase):
	"""WI name extraction from free text."""

	def _mod(self):
		from frappe_agile.api import github_webhook
		return github_webhook

	def test_extract_from_body(self):
		result = self._mod()._extract_wi_name("Closes WI-000042 as discussed", "", "")
		self.assertEqual(result, "WI-000042")

	def test_extract_from_title(self):
		result = self._mod()._extract_wi_name("", "[WI-7] fix login bug", "")
		self.assertEqual(result, "WI-7")

	def test_extract_from_branch(self):
		result = self._mod()._extract_wi_name("", "", "feature/WI-000001-add-login")
		self.assertEqual(result, "WI-000001")

	def test_priority_branch_over_body(self):
		"""_extract_wi_name returns the first match in argument order (branch, title, body)."""
		result = self._mod()._extract_wi_name("WI-000001-branch", "", "WI-000099 in body")
		self.assertEqual(result, "WI-000001")

	def test_returns_none_when_not_found(self):
		result = self._mod()._extract_wi_name("no match here", "also nothing", "fix-typo")
		self.assertIsNone(result)

	def test_case_insensitive(self):
		result = self._mod()._extract_wi_name("wi-000042", "", "")
		self.assertEqual(result, "WI-000042")


class TestResolveFrappeUser(unittest.TestCase):
	"""_resolve_frappe_user() GitHub → Frappe user mapping."""

	def _mod(self):
		from frappe_agile.api import github_webhook
		return github_webhook

	def _make_member(self, user: str, github_username: str):
		"""Create a mock Development Team Member row."""
		m = MagicMock()
		m.user = user
		m.github_username = github_username
		return m

	@patch("frappe.get_cached_doc")
	def test_resolves_matching_login(self, mock_get_cached):
		settings = MagicMock()
		settings.development_team = [
			self._make_member("alice@one-fm.com", "alice-gh"),
			self._make_member("bob@one-fm.com", "bob-gh"),
		]
		mock_get_cached.return_value = settings

		result = self._mod()._resolve_frappe_user("bob-gh")
		self.assertEqual(result, "bob@one-fm.com")

	@patch("frappe.get_cached_doc")
	def test_case_insensitive_match(self, mock_get_cached):
		settings = MagicMock()
		settings.development_team = [
			self._make_member("alice@one-fm.com", "Alice-GH"),
		]
		mock_get_cached.return_value = settings

		result = self._mod()._resolve_frappe_user("alice-gh")
		self.assertEqual(result, "alice@one-fm.com")

	@patch("frappe.get_cached_doc")
	def test_returns_none_when_no_match(self, mock_get_cached):
		settings = MagicMock()
		settings.development_team = [
			self._make_member("alice@one-fm.com", "alice-gh"),
		]
		mock_get_cached.return_value = settings

		result = self._mod()._resolve_frappe_user("unknown-user")
		self.assertIsNone(result)

	def test_returns_none_for_empty_login(self):
		result = self._mod()._resolve_frappe_user("")
		self.assertIsNone(result)

	def test_returns_none_for_none_login(self):
		result = self._mod()._resolve_frappe_user(None)
		self.assertIsNone(result)


class TestApplyWorkflowHelper(unittest.TestCase):
	"""_apply() helper behaviour."""

	def _mod(self):
		from frappe_agile.api import github_webhook
		return github_webhook

	@patch("frappe_agile.api.github_webhook.apply_workflow")
	@patch("frappe.get_doc")
	@patch("frappe.db.exists", return_value=True)
	@patch("frappe.set_user")
	def test_apply_calls_workflow(self, mock_set_user, _mock_exists, mock_get_doc, mock_apply):
		mod = self._mod()
		doc = MagicMock()
		doc.pr_link = ""
		doc.pr_reviewer_user = ""
		mock_get_doc.return_value = doc

		with patch("frappe.session") as sess:
			sess.user = "test@example.com"
			mod._apply("WI-000001", "Assign Reviewer", pr_url="https://github.com/p/1")

		mock_apply.assert_called_once_with(doc, "Assign Reviewer")
		doc.save.assert_called_once()

	@patch("frappe_agile.api.github_webhook.apply_workflow")
	@patch("frappe.get_doc")
	@patch("frappe.db.exists", return_value=True)
	@patch("frappe.set_user")
	def test_apply_sets_pr_reviewer_user(self, mock_set_user, _mock_exists, mock_get_doc, mock_apply):
		"""pr_reviewer_user should be set on the doc before workflow transition."""
		mod = self._mod()
		doc = MagicMock()
		doc.pr_link = ""
		doc.pr_reviewer_user = ""
		mock_get_doc.return_value = doc

		with patch("frappe.session") as sess:
			sess.user = "test@example.com"
			mod._apply(
				"WI-000001", "Assign Reviewer",
				pr_url="https://github.com/p/1",
				pr_reviewer_user="reviewer@one-fm.com",
			)

		self.assertEqual(doc.pr_reviewer_user, "reviewer@one-fm.com")
		mock_apply.assert_called_once_with(doc, "Assign Reviewer")

	@patch("frappe_agile.api.github_webhook.apply_workflow")
	@patch("frappe.get_doc")
	@patch("frappe.db.exists", return_value=True)
	@patch("frappe.set_user")
	def test_apply_does_not_overwrite_existing_reviewer(self, mock_set_user, _mock_exists, mock_get_doc, mock_apply):
		"""If pr_reviewer_user is already set, it should not be overwritten."""
		mod = self._mod()
		doc = MagicMock()
		doc.pr_link = ""
		doc.pr_reviewer_user = "existing@one-fm.com"
		mock_get_doc.return_value = doc

		with patch("frappe.session") as sess:
			sess.user = "test@example.com"
			mod._apply(
				"WI-000001", "Assign Reviewer",
				pr_url="https://github.com/p/1",
				pr_reviewer_user="new-reviewer@one-fm.com",
			)

		self.assertEqual(doc.pr_reviewer_user, "existing@one-fm.com")

	@patch("frappe.log_error")
	@patch("frappe.db.exists", return_value=False)
	def test_apply_logs_when_wi_not_found(self, _mock_exists, mock_log):
		mod = self._mod()
		mod._apply("WI-MISSING", "Assign Reviewer")
		mock_log.assert_called_once()
		self.assertIn("WI-MISSING", mock_log.call_args[1].get("message", ""))


class TestHandlePullRequest(unittest.TestCase):
	"""PR opened / merged routing."""

	def _mod(self):
		from frappe_agile.api import github_webhook
		return github_webhook

	@patch("frappe_agile.api.github_webhook._resolve_frappe_user", return_value="reviewer@one-fm.com")
	@patch("frappe_agile.api.github_webhook._apply")
	def test_pr_opened_with_reviewer_passes_user(self, mock_apply, _mock_resolve):
		"""PR opened with a requested reviewer should pass pr_reviewer_user to _apply."""
		mod = self._mod()
		payload = _build_pr_payload(
			action="opened",
			body="Closes WI-000042",
			requested_reviewers=[{"login": "octocat"}],
		)
		mod._handle_pull_request(payload)
		mock_apply.assert_called_once_with(
			"WI-000042", "Assign Reviewer",
			pr_url=ANY, pr_reviewer_user="reviewer@one-fm.com",
		)

	@patch("frappe_agile.api.github_webhook._resolve_frappe_user", return_value=None)
	@patch("frappe_agile.api.github_webhook._apply")
	def test_pr_opened_without_reviewer_passes_empty(self, mock_apply, _mock_resolve):
		"""PR opened with no requested reviewers should pass empty pr_reviewer_user."""
		mod = self._mod()
		payload = _build_pr_payload(
			action="opened",
			body="Closes WI-000042",
		)
		mod._handle_pull_request(payload)
		mock_apply.assert_called_once_with(
			"WI-000042", "Assign Reviewer",
			pr_url=ANY, pr_reviewer_user="",
		)

	@patch("frappe.log_error")
	@patch("frappe_agile.api.github_webhook._resolve_frappe_user", return_value=None)
	@patch("frappe_agile.api.github_webhook._apply")
	def test_pr_opened_with_unmapped_reviewer_logs_warning(self, mock_apply, _mock_resolve, mock_log):
		"""PR opened with a reviewer not in Dev Team should log a warning and still proceed."""
		mod = self._mod()
		payload = _build_pr_payload(
			action="opened",
			body="Closes WI-000042",
			requested_reviewers=[{"login": "unknown-dev"}],
		)
		mod._handle_pull_request(payload)
		# Should log that the reviewer could not be mapped
		mock_log.assert_called_once()
		self.assertIn("unknown-dev", mock_log.call_args[1].get("message", ""))
		# Should still proceed with the workflow transition
		mock_apply.assert_called_once()

	@patch("frappe_agile.api.github_webhook._apply")
	def test_pr_merged_merges_pr(self, mock_apply):
		mod = self._mod()
		payload = _build_pr_payload(
			action="closed",
			merged=True,
			body="Closes WI-000042",
		)
		mod._handle_pull_request(payload)
		mock_apply.assert_called_once_with("WI-000042", "Merge PR", pr_url=ANY)

	@patch("frappe_agile.api.github_webhook._apply")
	def test_pr_closed_not_merged_ignored(self, mock_apply):
		"""Closed but not merged — should not trigger any workflow action."""
		mod = self._mod()
		payload = _build_pr_payload(
			action="closed",
			merged=False,
			body="Closes WI-000042",
		)
		mod._handle_pull_request(payload)
		mock_apply.assert_not_called()

	@patch("frappe.log_error")
	@patch("frappe_agile.api.github_webhook._apply")
	def test_pr_opened_without_wi_logs_error(self, mock_apply, mock_log):
		mod = self._mod()
		payload = _build_pr_payload(action="opened", body="no reference here")
		mod._handle_pull_request(payload)
		mock_apply.assert_not_called()
		mock_log.assert_called_once()


class TestHandlePullRequestReview(unittest.TestCase):
	"""Review changes_requested routing."""

	def _mod(self):
		from frappe_agile.api import github_webhook
		return github_webhook

	@patch("frappe_agile.api.github_webhook._apply")
	def test_changes_requested_fires(self, mock_apply):
		mod = self._mod()
		payload = _build_review_payload(
			state="changes_requested",
			body="WI-000007 needs rework",
		)
		mod._handle_pull_request_review(payload)
		mock_apply.assert_called_once_with("WI-000007", "Request Changes", pr_url=ANY)

	@patch("frappe_agile.api.github_webhook._apply")
	def test_approved_review_ignored(self, mock_apply):
		mod = self._mod()
		payload = _build_review_payload(state="approved", body="WI-000007 looks good")
		mod._handle_pull_request_review(payload)
		mock_apply.assert_not_called()


class TestHandlePush(unittest.TestCase):
	"""Push event routing with guard logic."""

	def _mod(self):
		from frappe_agile.api import github_webhook
		return github_webhook

	@patch("frappe_agile.api.github_webhook._apply")
	@patch("frappe.db.get_value", return_value="Pending Execution")
	@patch("frappe.db.exists", return_value=True)
	def test_push_from_pending_execution_fires(self, _mock_exists, _mock_get, mock_apply):
		mod = self._mod()
		payload = _build_push_payload(ref="refs/heads/feature/WI-000001-task")
		mod._handle_push(payload)
		mock_apply.assert_called_once_with("WI-000001", "Execute Work Item")

	@patch("frappe_agile.api.github_webhook._apply")
	@patch("frappe.db.get_value", return_value="Pending Review")
	@patch("frappe.db.exists", return_value=True)
	def test_push_from_later_state_is_guarded(self, _mock_exists, _mock_get, mock_apply):
		"""Should NOT fire when WI is already past Pending PR."""
		mod = self._mod()
		payload = _build_push_payload(ref="refs/heads/feature/WI-000001-task")
		mod._handle_push(payload)
		mock_apply.assert_not_called()

	@patch("frappe_agile.api.github_webhook._apply")
	@patch("frappe.db.get_value", return_value="In Progress")
	@patch("frappe.db.exists", return_value=True)
	def test_push_from_wrong_state_is_guarded(self, _mock_exists, _mock_get, mock_apply):
		"""Should NOT fire when WI is not in Pending Execution."""
		mod = self._mod()
		payload = _build_push_payload(ref="refs/heads/feature/WI-000001-task")
		mod._handle_push(payload)
		mock_apply.assert_not_called()

	@patch("frappe_agile.api.github_webhook._apply")
	def test_push_without_wi_is_silent(self, mock_apply):
		"""Pushes with no WI reference should be silently ignored."""
		mod = self._mod()
		payload = _build_push_payload(ref="refs/heads/chore/fix-typo")
		mod._handle_push(payload)
		mock_apply.assert_not_called()

	@patch("frappe_agile.api.github_webhook._apply")
	@patch("frappe.db.get_value", return_value="Pending Execution")
	@patch("frappe.db.exists", return_value=True)
	def test_push_extracts_from_commit_message(self, _mock_exists, _mock_get, mock_apply):
		"""WI ID in a commit message should also be picked up."""
		mod = self._mod()
		payload = _build_push_payload(
			ref="refs/heads/feature/generic-branch",
			commit_messages=["fix(WI-000042): correct validation logic"],
		)
		mod._handle_push(payload)
		mock_apply.assert_called_once_with("WI-000042", "Execute Work Item")

	@patch("frappe.log_error")
	@patch("frappe_agile.api.github_webhook._apply")
	@patch("frappe.db.exists", return_value=False)
	def test_push_logs_when_wi_not_found(self, _mock_exists, mock_apply, mock_log):
		"""When WI is extracted but does not exist, an error should be logged."""
		mod = self._mod()
		payload = _build_push_payload(ref="refs/heads/feature/WI-000099-missing")
		mod._handle_push(payload)
		mock_apply.assert_not_called()
		mock_log.assert_called_once()
		self.assertIn("WI-000099", mock_log.call_args[1].get("message", ""))


# ---------------------------------------------------------------------------
# WI-003661: branch-first routing, response statuses, traceable Error Logs
# ---------------------------------------------------------------------------


def _mock_request(payload: dict, event: str = "pull_request", delivery_id: str = "delivery-abc-123"):
	req = MagicMock()
	req.headers = {"X-GitHub-Event": event, "X-GitHub-Delivery": delivery_id}
	req.data = json.dumps(payload).encode("utf-8")
	return req


def _full_pr_payload(branch: str, title: str, body: str, action: str = "opened") -> dict:
	payload = _build_pr_payload(action=action, body=body, title=title, branch=branch)
	payload["pull_request"]["number"] = 17
	payload["repository"] = {"full_name": "one-fm/frappe_agile"}
	payload["sender"] = {"login": "octocat"}
	return payload


def _mock_one_bpmn(send_message: MagicMock) -> dict:
	"""sys.modules entries so `from one_bpmn.api.instance_api import send_message` is mocked."""
	instance_api = MagicMock()
	instance_api.send_message = send_message
	return {
		"one_bpmn": MagicMock(),
		"one_bpmn.api": MagicMock(),
		"one_bpmn.api.instance_api": instance_api,
	}


class TestBranchFirstRouting(unittest.TestCase):
	"""PR events are routed by branch, then title, then body."""

	def _mod(self):
		from frappe_agile.api import github_webhook
		return github_webhook

	def _wi(self, n: int) -> str:
		return "WI-" + str(n).zfill(6)

	def test_branch_wins_over_body_for_pull_request(self):
		wi_a, wi_b = self._wi(11), self._wi(22)
		payload = _full_pr_payload(f"feature/{wi_a}-x", "no id here", f"Mentions {wi_b}")
		self.assertEqual(self._mod()._extract_wi_from_payload("pull_request", payload), wi_a)

	def test_title_wins_over_body_when_branch_has_no_id(self):
		wi_a, wi_b = self._wi(11), self._wi(22)
		payload = _full_pr_payload("feature/plain", f"[{wi_a}] fix", f"Mentions {wi_b}")
		self.assertEqual(self._mod()._extract_wi_from_payload("pull_request", payload), wi_a)

	def test_body_used_when_branch_and_title_have_no_id(self):
		wi_b = self._wi(22)
		payload = _full_pr_payload("feature/plain", "plain title", f"Mentions {wi_b}")
		self.assertEqual(self._mod()._extract_wi_from_payload("pull_request", payload), wi_b)

	def test_branch_wins_over_body_for_review(self):
		wi_a, wi_b = self._wi(11), self._wi(22)
		payload = _build_review_payload("approved", body=f"Mentions {wi_b}", branch=f"feature/{wi_a}-x")
		self.assertEqual(self._mod()._extract_wi_from_payload("pull_request_review", payload), wi_a)

	def test_message_goes_to_branch_work_item(self):
		"""End to end through the handler: delivery targets the branch's Work Item."""
		mod = self._mod()
		wi_a, wi_b = self._wi(11), self._wi(22)
		payload = _full_pr_payload(f"feature/{wi_a}-x", "title", f"Mentions {wi_b}")
		with patch("frappe.request", _mock_request(payload)), patch.object(
			mod, "_verify_signature"
		), patch.object(mod, "_deliver_bpmn_message", return_value={"status": "delivered"}) as deliver:
			mod.handle_github_webhook()
		self.assertEqual(deliver.call_args[0][0], wi_a)


class TestWebhookResponseStatuses(unittest.TestCase):
	"""One test per response status."""

	def _mod(self):
		from frappe_agile.api import github_webhook
		return github_webhook

	def _wi(self) -> str:
		return "WI-" + str(5001).zfill(6)

	def _deliver(self, exists, send_message=None, delivery=None):
		mod = self._mod()
		send_message = send_message or MagicMock(return_value={})
		response = {}
		with patch("frappe.db.exists", side_effect=exists), patch("frappe.set_user"), patch(
			"frappe.session", MagicMock(user="Guest")
		), patch("frappe.local.response", response, create=True), patch(
			"frappe.log_error"
		) as log, patch(
			"frappe.get_traceback", return_value="TRACEBACK-TEXT"
		), patch.dict(sys.modules, _mock_one_bpmn(send_message)):
			body = mod._deliver_bpmn_message(
				self._wi(), "github:pull_request:opened", {"a": 1}, delivery or {"delivery_id": "d-1"}
			)
		return body, response, log, send_message

	@staticmethod
	def _exists_ok(doctype, filters=None):
		return "found"

	def test_delivered(self):
		sm = MagicMock(return_value={"instance": "INST-1", "caught": True})
		body, response, log, _ = self._deliver(self._exists_ok, sm)
		self.assertEqual(body["status"], "delivered")
		self.assertEqual(body["work_item"], self._wi())
		self.assertEqual(body["message_name"], "github:pull_request:opened")
		self.assertEqual(body["instance"], "INST-1")
		self.assertNotIn("http_status_code", response)
		log.assert_not_called()

	def test_not_waiting(self):
		sm = MagicMock(return_value={"instance": "INST-1", "caught": False})
		body, response, log, _ = self._deliver(self._exists_ok, sm)
		self.assertEqual(body["status"], "not_waiting")
		self.assertEqual(body["instance"], "INST-1")
		self.assertEqual(body["work_item"], self._wi())
		self.assertNotIn("http_status_code", response)
		log.assert_not_called()

	def test_active_instance_check_uses_expected_filters(self):
		calls = []

		def exists(doctype, filters=None):
			calls.append((doctype, filters))
			return "found"

		self._deliver(exists, MagicMock(return_value={"instance": "I", "caught": True}))
		self.assertIn(
			(
				"BPMN Process Instance",
				{"context_doctype": "Work Item", "context_docname": self._wi(), "status": "Active"},
			),
			calls,
		)

	def test_work_item_not_found(self):
		sm = MagicMock()
		body, response, log, _ = self._deliver(lambda doctype, filters=None: None, sm)
		self.assertEqual(body["status"], "work_item_not_found")
		self.assertEqual(body["work_item"], self._wi())
		self.assertIn("message_name", body)
		self.assertEqual(response["http_status_code"], 404)
		log.assert_called_once()
		sm.assert_not_called()

	def test_no_active_instance(self):
		def exists(doctype, filters=None):
			return "found" if doctype == "Work Item" else None

		sm = MagicMock()
		body, response, log, _ = self._deliver(exists, sm)
		self.assertEqual(body["status"], "no_active_instance")
		self.assertEqual(body["work_item"], self._wi())
		self.assertIn("message_name", body)
		self.assertEqual(response["http_status_code"], 500)
		log.assert_called_once()
		self.assertEqual(log.call_args[1]["reference_name"], self._wi())
		sm.assert_not_called()

	def test_failed(self):
		sm = MagicMock(side_effect=RuntimeError("boom"))
		body, response, log, _ = self._deliver(self._exists_ok, sm)
		self.assertEqual(body["status"], "failed")
		self.assertEqual(body["error"], "boom")
		self.assertEqual(body["work_item"], self._wi())
		self.assertEqual(response["http_status_code"], 500)
		log.assert_called_once()
		self.assertIn("TRACEBACK-TEXT", log.call_args[1]["message"])

	def test_no_work_item(self):
		mod = self._mod()
		payload = _full_pr_payload("feature/plain-branch", "Plain title", "no reference")
		with patch("frappe.request", _mock_request(payload)), patch.object(
			mod, "_verify_signature"
		), patch("frappe.log_error") as log:
			body = mod.handle_github_webhook()
		self.assertEqual(body["status"], "no_work_item")
		log.assert_called_once()
		message = log.call_args[1]["message"]
		self.assertIn("feature/plain-branch", message)
		self.assertIn("Plain title", message)


class TestWebhookErrorLogDetails(unittest.TestCase):
	"""Error Logs name the delivery and are linked to the Work Item."""

	def _mod(self):
		from frappe_agile.api import github_webhook
		return github_webhook

	def test_error_log_has_delivery_id_repository_and_reference(self):
		mod = self._mod()
		wi_name = "WI-" + str(77).zfill(6)
		payload = _full_pr_payload(f"feature/{wi_name}-x", "title", "body")
		response = {}
		with patch("frappe.request", _mock_request(payload, delivery_id="delivery-xyz-789")), patch.object(
			mod, "_verify_signature"
		), patch("frappe.db.exists", side_effect=lambda doctype, filters=None: "x" if doctype == "Work Item" else None), patch(
			"frappe.set_user"
		), patch("frappe.session", MagicMock(user="Guest")), patch(
			"frappe.local.response", response, create=True
		), patch("frappe.log_error") as log, patch.dict(
			sys.modules, _mock_one_bpmn(MagicMock())
		):
			body = mod.handle_github_webhook()

		self.assertEqual(body["status"], "no_active_instance")
		log.assert_called_once()
		kwargs = log.call_args[1]
		self.assertIn("delivery-xyz-789", kwargs["message"])
		self.assertIn("one-fm/frappe_agile", kwargs["message"])
		self.assertIn("octocat", kwargs["message"])
		self.assertEqual(kwargs["reference_doctype"], "Work Item")
		self.assertEqual(kwargs["reference_name"], wi_name)


class TestVerifySignatureDeferredLog(unittest.TestCase):
	"""Signature Error Logs survive the rollback of the failed request."""

	def _mod(self):
		from frappe_agile.api import github_webhook
		return github_webhook

	def test_signature_mismatch_logs_with_defer_insert(self):
		mod = self._mod()
		req = MagicMock()
		req.headers = {"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Delivery": "delivery-sig-1"}
		req.data = b"{}"
		with patch("frappe.request", req), patch.object(
			mod, "_get_webhook_secret", return_value="test-secret"
		), patch("frappe.log_error") as log:
			with self.assertRaises(frappe.exceptions.AuthenticationError):
				mod._verify_signature()
		log.assert_called_once()
		self.assertIs(log.call_args[1].get("defer_insert"), True)
		self.assertIn("delivery-sig-1", log.call_args[1]["message"])

	def test_configuration_error_logs_with_defer_insert(self):
		mod = self._mod()
		req = MagicMock()
		req.headers = {"X-GitHub-Delivery": "delivery-cfg-1"}
		req.data = b"{}"
		with patch("frappe.request", req), patch.object(
			mod, "_get_webhook_secret", return_value=None
		), patch("frappe.log_error") as log:
			with self.assertRaises(frappe.exceptions.AuthenticationError):
				mod._verify_signature()
		self.assertIs(log.call_args[1].get("defer_insert"), True)


if __name__ == "__main__":
	unittest.main()
