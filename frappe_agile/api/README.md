# `frappe_agile/api` — GitHub Webhook

Whitelisted Frappe endpoint that receives GitHub Organisation webhook events and
automatically advances **Work Item** workflow states.

---

## Endpoint

```
POST https://<your-site>/api/method/frappe_agile.api.github_webhook.handle_github_webhook
```

---

## GitHub Configuration

1. Go to **GitHub → Organisation (or Repo) → Settings → Webhooks → Add webhook**

   | Field | Value |
   |---|---|
   | **Payload URL** | `https://<your-site>/api/method/frappe_agile.api.github_webhook.handle_github_webhook` |
   | **Content type** | `application/json` |
   | **Secret** | Same value as `github_webhook_secret` in `site_config.json` |
   | **Events** | ☑ Pull requests &nbsp;☑ Pull request reviews &nbsp;☑ Pushes |

2. Add the secret to your Frappe site config:

   ```bash
   # sites/<your-site>/site_config.json
   {
     "github_webhook_secret": "your-strong-secret-here"
   }
   ```

3. Restart workers:
   ```bash
   bench restart
   ```

---

## Security

Every incoming request is validated using **HMAC-SHA256** against the
`X-Hub-Signature-256` header. Requests with a missing or mismatched signature
are rejected with HTTP 401 and logged via `frappe.log_error`.

---

## Event Handling & State Mapping

### `pull_request`

| `action` | `merged` | Workflow Action | Work Item State |
|---|---|---|---|
| `opened` | — | Assign Reviewer | **Pending Review** |
| `closed` | `true` | Merge PR | **In Staging** |
| `closed` | `false` | *(ignored)* | — |

**Example payload (PR opened):**
```json
{
  "action": "opened",
  "pull_request": {
    "html_url": "https://github.com/org/repo/pull/42",
    "merged": false,
    "title": "Fix login bug",
    "body": "Closes WI-000007. Added null check on session.",
    "head": { "ref": "feature/WI-000007-fix-login" }
  }
}
```

---

### `pull_request_review`

| `review.state` | Workflow Action | Work Item State |
|---|---|---|
| `changes_requested` | Request Changes | **Changes Requested** |
| anything else | *(ignored)* | — |

**Example payload:**
```json
{
  "review": { "state": "changes_requested" },
  "pull_request": {
    "html_url": "https://github.com/org/repo/pull/42",
    "title": "Fix login bug",
    "body": "WI-000007",
    "head": { "ref": "feature/fix-login" }
  }
}
```

---

### `push`

Transitions Work Item from **Pending Execution → Pending PR** only.
If the Work Item is already at `Pending Review` or later, it is **not touched**
(no rollback).

| Condition | Workflow Action | Work Item State |
|---|---|---|
| `workflow_state == "Pending Execution"` | Execute Work Item | **Pending PR** |
| Already past Pending PR | *(skipped)* | — |

**Example payload:**
```json
{
  "ref": "refs/heads/feature/WI-000007-fix-login",
  "commits": [
    { "message": "fix(WI-000007): add null check on session" }
  ]
}
```

---

## Work Item ID Extraction

The handler searches for `WI-\d+` (case-insensitive) in this priority order:

1. **PR body** — e.g., `Closes WI-000042` or `Linked to WI-42`
2. **PR title** — e.g., `[WI-42] Fix login`
3. **Branch name** — e.g., `feature/WI-000042-add-auth`
4. **Commit messages** *(push events only)*

If no Work Item ID is found, the event is logged and silently skipped.

---

## Error Handling

All errors are recorded in **Frappe Error Log** (desk → `Error Log` DocType):

| Situation | Log title |
|---|---|
| Bad / missing HMAC signature | `GitHub Webhook – signature mismatch` |
| Malformed JSON body | `GitHub Webhook – malformed JSON payload` |
| Work Item not found | `GitHub Webhook – Work Item not found` |
| No WI-ID in payload | `GitHub Webhook – no Work Item ID found (...)` |
| `apply_workflow` permission error | `GitHub Webhook – workflow permission error on WI-XXXXXX` |
| Any other exception | `GitHub Webhook – unexpected error applying '...' to WI-XXXXXX` |

---

## Manual curl Test

```bash
SECRET="your_secret"
PAYLOAD='{"action":"opened","pull_request":{"html_url":"https://github.com/org/repo/pull/1","merged":false,"title":"","body":"WI-000001 fix","head":{"ref":"feature/fix"}}}'
SIG="sha256=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')"

curl -X POST \
  "https://your-site.com/api/method/frappe_agile.api.github_webhook.handle_github_webhook" \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: pull_request" \
  -H "X-Hub-Signature-256: $SIG" \
  -d "$PAYLOAD"
# → {"message": {"status": "ok"}}
```

---

## Running Tests

```bash
bench --site onefm run-tests --app frappe_agile --module frappe_agile.api.test_github_webhook
```
