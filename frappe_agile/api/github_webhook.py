# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""
GitHub Organisation Webhook handler for frappe_agile.

Architecture
------------
This is a **thin, generic router** with zero business logic.  It receives
GitHub webhook events, verifies the HMAC signature, extracts the linked
Work Item, derives a convention-based BPMN message name from the event
data, and delivers it to the active BPMN process instance via
``one_bpmn.api.send_message``.

All business logic (state transitions, assignments, notifications) lives
in the BPMN process diagram — not here.

Entry point
-----------
Payload URL:
	https://<your-site>/api/method/frappe_agile.api.github_webhook.handle_github_webhook

GitHub App/Org Settings → Webhooks
	Content type : application/json
	Secret       : <value stored in Frappe Agile Settings → GitHub Webhook Secret>
	Events       : Pull requests, Pull request reviews, Pushes

Message name convention
-----------------------
Message names are derived deterministically from the GitHub event::

	github:<event_type>:<action>

Examples:
	github:pull_request:opened
	github:pull_request:merged
	github:pull_request_review:changes_requested
	github:push

The BA uses these exact names as ``<bpmn:message name="...">`` in the
process diagram.  No backend changes are needed when new events are added
— just update the diagram.

Configuration
-------------
Set the webhook secret via:
  1. (Preferred) Frappe → Frappe Agile Settings → GitHub Integration → GitHub Webhook Secret
  2. (Legacy fallback) site_config.json: "github_webhook_secret": "<your-secret-here>"
"""

import hashlib
import hmac
import json
import re

import frappe
from frappe import _
from frappe.utils.password import get_decrypted_password

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Regex that matches a Work Item name anywhere in free text
# Matches patterns like WI-000001, WI-1, WI-123456 etc.
_WI_PATTERN = re.compile(r"\bWI-\d+\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public endpoint
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True)
def handle_github_webhook():
	"""
	Receive and route a GitHub organisation webhook event to BPMN.

	Security
	--------
	Validates the HMAC-SHA256 signature sent in the ``X-Hub-Signature-256``
	header.  If absent or invalid the request is rejected with a 401.

	Flow
	----
	1. Verify HMAC signature
	2. Parse the JSON payload
	3. Derive a convention-based BPMN message name from the event
	4. Extract the linked Work Item ID from the PR/commit/branch
	5. Build a clean payload dict with relevant data
	6. Deliver the message to the BPMN engine via ``send_message()``

	The webhook handler contains **no business logic** — all routing and
	state transitions are defined in the BPMN process diagram.
	"""
	_verify_signature()

	event_type = frappe.request.headers.get("X-GitHub-Event", "")
	try:
		payload = json.loads(frappe.request.data)
	except (json.JSONDecodeError, AttributeError) as exc:
		frappe.log_error(
			title="GitHub Webhook – malformed JSON payload",
			message=str(exc),
		)
		frappe.throw(_("Invalid JSON payload"), frappe.ValidationError)

	# ── 1. Derive message name ───────────────────────────────────────────
	message_name = _derive_message_name(event_type, payload)
	if not message_name:
		# Unhandled or irrelevant event (ping, etc.) — silently ignore
		return {"status": "ignored"}

	# ── 2. Extract Work Item ID ──────────────────────────────────────────
	wi_name = _extract_wi_from_payload(event_type, payload)
	if not wi_name:
		frappe.log_error(
			title=f"GitHub Webhook – no Work Item ID found ({event_type})",
			message=(
				f"Event '{message_name}' — could not find a WI-XXXXXX "
				"reference in the PR body, title, branch name, or commit messages."
			),
		)
		return {"status": "no_work_item"}

	# ── 3. Build message payload ─────────────────────────────────────────
	msg_payload = _build_message_payload(event_type, payload)

	# ── 4. Deliver to BPMN engine ────────────────────────────────────────
	_deliver_bpmn_message(wi_name, message_name, msg_payload)

	return {"status": "ok"}


# ---------------------------------------------------------------------------
# Message name derivation
# ---------------------------------------------------------------------------


def _derive_message_name(event_type: str, payload: dict) -> str | None:
	"""
	Derive a BPMN message name from the GitHub event type and payload.

	Convention: ``github:<event_type>:<action>``

	Special cases:
	    - pull_request closed + merged → ``github:pull_request:merged``
	    - pull_request closed (not merged) → ``github:pull_request:closed``
	    - pull_request_review → uses review.state (e.g. ``changes_requested``)

	Returns None for events we don't route (ping, etc.).
	"""
	if event_type == "pull_request":
		action = payload.get("action", "")
		pr = payload.get("pull_request", {})

		# Distinguish merged from simply closed
		if action == "closed" and pr.get("merged"):
			return "github:pull_request:merged"
		elif action == "closed":
			return "github:pull_request:closed"
		elif action:
			return f"github:pull_request:{action}"
		return None

	elif event_type == "pull_request_review":
		review = payload.get("review", {})
		state = review.get("state", "").lower()
		if state:
			return f"github:pull_request_review:{state}"
		return None

	elif event_type == "push":
		return "github:push"

	# Ignore ping, check_suite, etc.
	return None


# ---------------------------------------------------------------------------
# Work Item extraction
# ---------------------------------------------------------------------------


def _extract_wi_from_payload(event_type: str, payload: dict) -> str | None:
	"""
	Extract the Work Item ID from the appropriate fields based on event type.

	- pull_request / pull_request_review → PR body, title, branch name
	- push → commit messages, branch name
	"""
	if event_type in ("pull_request", "pull_request_review"):
		pr = payload.get("pull_request", {})
		return _extract_wi_name(
			pr.get("body") or "",
			pr.get("title") or "",
			pr.get("head", {}).get("ref") or "",
		)
	elif event_type == "push":
		ref = payload.get("ref", "")
		branch_name = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
		commits = payload.get("commits", [])
		commit_messages = " ".join(c.get("message", "") for c in commits)
		return _extract_wi_name(commit_messages, branch_name)

	return None


def _extract_wi_name(*texts: str) -> str | None:
	"""
	Search each text string in order and return the first WI-\\d+ match,
	upper-cased, or None if not found.
	"""
	for text in texts:
		match = _WI_PATTERN.search(text or "")
		if match:
			return match.group(0).upper()
	return None


# ---------------------------------------------------------------------------
# Message payload construction
# ---------------------------------------------------------------------------


def _build_message_payload(event_type: str, payload: dict) -> dict:
	"""
	Build a clean, serializable payload dict from the GitHub event.

	Only includes fields that are useful for BPMN process conditions and
	downstream tasks.  The full raw payload is NOT forwarded (too large
	and not serializable by SpiffWorkflow).
	"""
	result = {
		"event_type": event_type,
	}

	if event_type in ("pull_request", "pull_request_review"):
		pr = payload.get("pull_request", {})
		result["pr_url"] = pr.get("html_url", "")
		result["pr_title"] = pr.get("title", "")
		result["pr_number"] = pr.get("number", 0)
		result["pr_state"] = pr.get("state", "")
		result["pr_merged"] = pr.get("merged", False)
		result["branch"] = pr.get("head", {}).get("ref", "")
		result["base_branch"] = pr.get("base", {}).get("ref", "")
		result["pr_author"] = pr.get("user", {}).get("login", "")

		# PR action
		result["action"] = payload.get("action", "")

		# Requested reviewers
		reviewers = pr.get("requested_reviewers") or []
		result["reviewer_github_login"] = reviewers[0].get("login", "") if reviewers else ""

	if event_type == "pull_request_review":
		review = payload.get("review", {})
		result["review_state"] = review.get("state", "")
		result["reviewer_github_login"] = review.get("user", {}).get("login", "")

	if event_type == "push":
		ref = payload.get("ref", "")
		result["branch"] = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
		result["pusher"] = payload.get("pusher", {}).get("name", "")
		commits = payload.get("commits", [])
		result["commit_count"] = len(commits)
		result["head_commit_message"] = payload.get("head_commit", {}).get("message", "")

	return result


# ---------------------------------------------------------------------------
# BPMN message delivery
# ---------------------------------------------------------------------------


def _deliver_bpmn_message(wi_name: str, message_name: str, payload: dict):
	"""
	Deliver a BPMN message to the active process instance for a Work Item.

	Best-effort delivery — if there is no active BPMN instance or no task
	is waiting for this message, the error is logged and the function
	returns gracefully.

	Runs as Administrator since webhooks arrive without a Frappe session.
	"""
	if not frappe.db.exists("Work Item", wi_name):
		frappe.log_error(
			title=f"GitHub Webhook – Work Item not found",
			message=f"Work Item '{wi_name}' does not exist. Message '{message_name}' not delivered.",
		)
		return

	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		from one_bpmn.api import send_message

		result = send_message(
			message_name=message_name,
			context_doctype="Work Item",
			context_docname=wi_name,
			payload=json.dumps(payload),
		)
		print(f"GitHub Webhook → BPMN: '{message_name}' → {wi_name} → {result.get('status', '?')}")
	except Exception:
		# Best-effort: log and continue.
		frappe.log_error(
			title=f"GitHub Webhook – BPMN message delivery failed",
			message=(
				f"Message '{message_name}' to Work Item '{wi_name}' failed.\n"
				f"{frappe.get_traceback()}"
			),
		)
	finally:
		frappe.set_user(original_user)


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


def _get_webhook_secret() -> str | None:
	"""
	Return the GitHub webhook secret.

	Lookup order:
	1. Frappe Agile Settings → ``github_webhook_secret`` (preferred – managed via UI).
	2. ``frappe.conf.github_webhook_secret`` in site_config.json (legacy fallback).

	Returns ``None`` when neither source is configured.
	"""
	# Password fields are stored encrypted in the __Auth table.
	# get_decrypted_password returns the plaintext secret;
	# get_single_value would return the masked placeholder ('*').
	settings_secret = get_decrypted_password(
		"Frappe Agile Settings",
		"Frappe Agile Settings",
		fieldname="github_webhook_secret",
		raise_exception=False,
	)
	if settings_secret:
		return settings_secret

	# Legacy fallback: site_config.json
	return frappe.conf.get("github_webhook_secret")


def _verify_signature():
	"""
	Validate the X-Hub-Signature-256 header using HMAC-SHA256.

	The secret is resolved via :func:`_get_webhook_secret` (settings first,
	then site_config.json fallback).
	Raises ``frappe.AuthenticationError`` if verification fails.
	"""
	secret = _get_webhook_secret()
	if not secret:
		frappe.log_error(
			title="GitHub Webhook – configuration error",
			message=(
				"GitHub Webhook Secret is not configured. "
				"Set it in Frappe Agile Settings → GitHub Integration → GitHub Webhook Secret, "
				"or add 'github_webhook_secret' to site_config.json (legacy)."
			),
		)
		frappe.throw(
			_(
				"Webhook secret not configured. "
				"Set it in Frappe Agile Settings (preferred) "
				"or in site_config.json as 'github_webhook_secret' (legacy)."
			),
			frappe.AuthenticationError,
		)

	signature_header = frappe.request.headers.get("X-Hub-Signature-256", "")
	if not signature_header.startswith("sha256="):
		frappe.throw(
			_("Missing or malformed X-Hub-Signature-256 header."),
			frappe.AuthenticationError,
		)

	received_sig = signature_header[len("sha256="):]
	raw_body = frappe.request.data or b""
	expected_sig = hmac.new(
		key=secret.encode("utf-8"),
		msg=raw_body,
		digestmod=hashlib.sha256,
	).hexdigest()

	if not hmac.compare_digest(received_sig, expected_sig):
		# Log only that a mismatch occurred; avoid logging full digest values.
		frappe.log_error(
			title="GitHub Webhook – signature mismatch",
			message=(
				f"Signature mismatch for incoming webhook request "
				f"(received prefix: sha256={received_sig[:8]}...). "
				"Verify that the webhook secret in Frappe Agile Settings "
				"(or 'github_webhook_secret' in site_config.json if using legacy fallback) "
				"matches the secret configured in GitHub."
			),
		)
		frappe.throw(
			_("GitHub webhook signature verification failed."),
			frappe.AuthenticationError,
		)
