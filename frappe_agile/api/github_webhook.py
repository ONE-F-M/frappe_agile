# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""
GitHub Organisation Webhook handler for frappe_agile.

Entry point
-----------
Payload URL:
	https://<your-site>/api/method/frappe_agile.api.github_webhook.handle_github_webhook

GitHub App/Org Settings → Webhooks
	Content type : application/json
	Secret       : <value of frappe.conf.github_webhook_secret>
	Events       : Pull requests, Pull request reviews, Pushes

site_config.json (bench/sites/<site>/site_config.json)
	"github_webhook_secret": "<your-secret-here>"

Work Item workflow states being targeted
-----------------------------------------
	Pending PR       ← push (Execute Work Item transition, only from Pending Execution)
	Pending Review   ← PR opened (Assign Reviewer transition)
	Changes Requested← review changes_requested (Request Changes transition)
	In Staging       ← PR merged (Merge PR transition)
"""

import hashlib
import hmac
import json
import re

import frappe
from frappe import _
from frappe.model.workflow import WorkflowTransitionError, apply_workflow

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Regex that matches a Work Item name anywhere in free text
# Matches patterns like WI-000001, WI-1, WI-123456 etc.
_WI_PATTERN = re.compile(r"\bWI-\d+\b", re.IGNORECASE)

# States that are considered "later" than Pending PR in the pipeline.
# A push event will NOT roll back a Work Item already past this point.
_LATER_THAN_PENDING_PR = {
	"Pending Review",
	"Changes Requested",
	"In Staging",
	"Done",
	"Rejected",
}

# ---------------------------------------------------------------------------
# Public endpoint
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True)
def handle_github_webhook():
	"""
	Receive and process a GitHub organisation webhook event.

	Security
	--------
	Validates the HMAC-SHA256 signature sent in the ``X-Hub-Signature-256``
	header against ``frappe.conf.github_webhook_secret``.  If absent or
	invalid the request is rejected with a 401.

	Event routing
	-------------
	X-GitHub-Event: pull_request        → _handle_pull_request()
	X-GitHub-Event: pull_request_review → _handle_pull_request_review()
	X-GitHub-Event: push                → _handle_push()
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

	if event_type == "pull_request":
		_handle_pull_request(payload)
	elif event_type == "pull_request_review":
		_handle_pull_request_review(payload)
	elif event_type == "push":
		_handle_push(payload)
	else:
		# Silently ignore unhandled events (ping, etc.)
		pass

	return {"status": "ok"}


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def _handle_pull_request(payload: dict):
	"""
	PR opened  → "Assign Reviewer"  → Pending Review
	PR merged  → "Merge PR"         → In Staging
	"""
	action = payload.get("action", "")
	pr = payload.get("pull_request", {})
	pr_url = pr.get("html_url", "")
	merged = pr.get("merged", False)

	# Extract Work Item ID from PR body, title, or branch name (in that order)
	wi_name = _extract_wi_name(
		pr.get("body") or "",
		pr.get("title") or "",
		pr.get("head", {}).get("ref") or "",
	)
	if not wi_name:
		frappe.log_error(
			title="GitHub Webhook – no Work Item ID found (pull_request)",
			message=(
				f"PR action='{action}' url='{pr_url}' — could not find a WI-XXXXXX "
				"reference in the PR body, title, or branch name."
			),
		)
		return

	if action == "opened":
		# If the WI is still in Pending Execution (push webhook never fired),
		# auto-advance it to Pending PR first, then assign the reviewer.
		current_state = frappe.db.get_value("Work Item", wi_name, "workflow_state") if frappe.db.exists("Work Item", wi_name) else None
		if current_state == "Pending Execution":
			_apply(wi_name, "Execute Work Item", pr_url=pr_url)
		_apply(wi_name, "Assign Reviewer", pr_url=pr_url)

	elif action == "closed" and merged:
		_apply(wi_name, "Merge PR", pr_url=pr_url)


def _handle_pull_request_review(payload: dict):
	"""
	Review state == changes_requested → "Request Changes" → Changes Requested
	"""
	review = payload.get("review", {})
	pr = payload.get("pull_request", {})
	pr_url = pr.get("html_url", "")

	if review.get("state", "").lower() != "changes_requested":
		return

	wi_name = _extract_wi_name(
		pr.get("body") or "",
		pr.get("title") or "",
		pr.get("head", {}).get("ref") or "",
	)
	if not wi_name:
		frappe.log_error(
			title="GitHub Webhook – no Work Item ID found (pull_request_review)",
			message=(
				f"Review changes_requested on PR url='{pr_url}' — could not find a "
				"WI-XXXXXX reference in the PR body, title, or branch name."
			),
		)
		return

	_apply(wi_name, "Request Changes", pr_url=pr_url)


def _handle_push(payload: dict):
	"""
	Branch pushed → "Execute Work Item" → Pending PR
	(only when the Work Item is currently in 'Pending Execution')
	"""
	ref = payload.get("ref", "")  # e.g. "refs/heads/feature/WI-000001-my-task"
	branch_name = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref

	# For push events the Work Item reference is taken from commit messages
	# first, then the branch name (commit messages are more explicit).
	commits = payload.get("commits", [])
	commit_messages = " ".join(c.get("message", "") for c in commits)

	wi_name = _extract_wi_name(commit_messages, branch_name)
	if not wi_name:
		# Not every push has a WI reference — silently ignore.
		return

	# Verify the Work Item exists before trying to read its state.
	if not frappe.db.exists("Work Item", wi_name):
		frappe.log_error(
			title="GitHub Webhook – Work Item not found (push)",
			message=(
				f"Work Item '{wi_name}' found in push ref/commit messages "
				f"(ref='{ref}') but does not exist in the system."
			),
		)
		return

	current_state = frappe.db.get_value("Work Item", wi_name, "workflow_state")

	# Guard: workflow_state may be None if the workflow was never applied.
	if not current_state:
		frappe.log_error(
			title="GitHub Webhook – missing workflow_state (push)",
			message=(
				f"Work Item '{wi_name}' has no workflow_state set. "
				"Ensure the Work Item workflow is active and the document has been saved."
			),
		)
		return

	# Guard: only advance from Pending Execution; never roll back.
	if current_state in _LATER_THAN_PENDING_PR:
		return  # Already past Pending PR, do not touch it.

	if current_state != "Pending Execution":
		return  # Not in the right state for this transition.

	_apply(wi_name, "Execute Work Item")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _apply(wi_name: str, action: str, pr_url: str = ""):
	"""
	Apply a workflow action to a Work Item, running as Administrator so that
	role-based guards inside the workflow are bypassed for this service call.

	If the Work Item does not exist, or the transition is not valid from the
	current state, the error is logged and the function returns gracefully.
	"""
	if not frappe.db.exists("Work Item", wi_name):
		frappe.log_error(
			title="GitHub Webhook – Work Item not found",
			message=f"Work Item '{wi_name}' referenced in PR '{pr_url}' does not exist.",
		)
		return

	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Work Item", wi_name)

		# Optionally capture the PR link when available
		if pr_url and hasattr(doc, "pr_link") and not doc.pr_link:
			doc.pr_link = pr_url

		apply_workflow(doc, action)
		doc.save(ignore_permissions=True)

		print(f"GitHub Webhook: applied '{action}' to {wi_name} (PR: {pr_url or 'n/a'})")

	except WorkflowTransitionError as exc:
		current_state = frappe.db.get_value("Work Item", wi_name, "workflow_state")
		frappe.log_error(
			title=f"GitHub Webhook – invalid transition '{action}' on {wi_name}",
			message=(
				f"Action '{action}' is not valid from current state '{current_state}'. "
				f"PR: {pr_url or 'n/a'}. Error: {exc}"
			),
		)
	except Exception:  # noqa: BLE001
		frappe.log_error(
			title=f"GitHub Webhook – unexpected error applying '{action}' to {wi_name}",
			message=frappe.get_traceback(),
		)
	finally:
		frappe.set_user(original_user)


def _verify_signature():
	"""
	Validate the X-Hub-Signature-256 header using HMAC-SHA256.

	The secret is read from ``frappe.conf.github_webhook_secret``.
	Raises ``frappe.AuthenticationError`` if verification fails.
	"""
	secret = frappe.conf.get("github_webhook_secret")
	if not secret:
		frappe.log_error(
			title="GitHub Webhook – configuration error",
			message=(
				"'github_webhook_secret' is not set in site_config.json. "
				"Add it to enable webhook signature validation."
			),
		)
		frappe.throw(
			_("Webhook secret not configured on this site."),
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
				"Verify that github_webhook_secret in site_config.json matches "
				"the secret configured in GitHub."
			),
		)
		frappe.throw(
			_("GitHub webhook signature verification failed."),
			frappe.AuthenticationError,
		)
