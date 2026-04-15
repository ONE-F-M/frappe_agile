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
) -> dict:
	return {
		"action": action,
		"pull_request": {
			"html_url": pr_url,
			"merged": merged,
			"body": body,
			"title": title,
			"head": {"ref": branch},
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
	@patch("frappe.get_single_value", return_value="settings-secret")
	def test_settings_secret_takes_priority(self, _mock_single, _mock_conf):
		"""When both Settings and conf have a secret, Settings wins."""
		_mock_conf.get.return_value = "conf-secret"
		result = self._mod()._get_webhook_secret()
		self.assertEqual(result, "settings-secret")

	@patch("frappe.conf")
	@patch("frappe.get_single_value", return_value="settings-secret")
	def test_settings_secret_only(self, _mock_single, _mock_conf):
		"""When only Settings has a secret, it should be returned."""
		_mock_conf.get.return_value = None
		result = self._mod()._get_webhook_secret()
		self.assertEqual(result, "settings-secret")

	@patch("frappe.conf")
	@patch("frappe.get_single_value", return_value=None)
	def test_conf_fallback(self, _mock_single, _mock_conf):
		"""When Settings is empty, should fall back to frappe.conf."""
		_mock_conf.get.return_value = "conf-secret"
		result = self._mod()._get_webhook_secret()
		self.assertEqual(result, "conf-secret")

	@patch("frappe.conf")
	@patch("frappe.get_single_value", return_value=None)
	def test_returns_none_when_not_configured(self, _mock_single, _mock_conf):
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
				mod._verify_signature()

	def test_missing_signature_raises(self):
		"""Missing header should raise AuthenticationError."""
		mod = self._mod()
		mock_request = MagicMock()
		mock_request.headers = {}
		mock_request.data = b"{}"

		with patch("frappe.request", mock_request):
			with patch("frappe_agile.api.github_webhook._get_webhook_secret", return_value="test-secret"):
				with self.assertRaises(frappe.exceptions.AuthenticationError):
					mod._verify_signature()

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
					mod._verify_signature()

	def test_no_secret_configured_raises(self):
		"""When no secret is configured anywhere, should raise AuthenticationError."""
		mod = self._mod()
		mock_request = MagicMock()
		mock_request.headers = {"X-Hub-Signature-256": "sha256=abc"}
		mock_request.data = b"{}"

		with patch("frappe.request", mock_request):
			with patch("frappe_agile.api.github_webhook._get_webhook_secret", return_value=None):
				with self.assertRaises(frappe.exceptions.AuthenticationError):
					mod._verify_signature()


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

	def test_priority_body_over_branch(self):
		result = self._mod()._extract_wi_name("WI-000099 in body", "", "WI-000001-branch")
		self.assertEqual(result, "WI-000099")

	def test_returns_none_when_not_found(self):
		result = self._mod()._extract_wi_name("no match here", "also nothing", "fix-typo")
		self.assertIsNone(result)

	def test_case_insensitive(self):
		result = self._mod()._extract_wi_name("wi-000042", "", "")
		self.assertEqual(result, "WI-000042")


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
		mock_get_doc.return_value = doc

		with patch("frappe.session") as sess:
			sess.user = "test@example.com"
			mod._apply("WI-000001", "Assign Reviewer", pr_url="https://github.com/p/1")

		mock_apply.assert_called_once_with(doc, "Assign Reviewer")
		doc.save.assert_called_once()

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

	@patch("frappe_agile.api.github_webhook._apply")
	def test_pr_opened_assigns_reviewer(self, mock_apply):
		mod = self._mod()
		payload = _build_pr_payload(
			action="opened",
			body="Closes WI-000042",
		)
		mod._handle_pull_request(payload)
		mock_apply.assert_called_once_with("WI-000042", "Assign Reviewer", pr_url=ANY)

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


if __name__ == "__main__":
	unittest.main()
