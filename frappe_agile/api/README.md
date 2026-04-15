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
   | **Secret** | Same value as configured in Frappe Agile Settings (see step 2) |
   | **Events** | ☑ Pull requests &nbsp;☑ Pull request reviews &nbsp;☑ Pushes |

2. Configure the webhook secret in Frappe:

   **Preferred (via UI):**
   Go to **Frappe Agile Settings → GitHub Integration → GitHub Webhook Secret** and enter your secret.

   **Legacy fallback (via site_config.json):**
   ```bash
   bench --site <your-site> set-config github_webhook_secret "your-strong-secret-here"
   ```

   > The webhook handler checks Frappe Agile Settings first. If empty, it falls back to `github_webhook_secret` in `site_config.json`.

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

| `action` | `merged` | Workflow Action | Work Item State | Side Effects |
|---|---|---|---|---|
| `opened` | — | Assign Reviewer | **Pending Review** | Sets `pr_link`, resolves `pr_reviewer_user` from `requested_reviewers` |
| `closed` | `true` | Merge PR | **In Staging** | Sets `pr_link` |
| `closed` | `false` | *(ignored)* | — | — |

When a PR is **opened**, the webhook also:
1. Sets `pr_link` to the PR URL (if not already set).
2. Extracts the first `requested_reviewers[].login` from the payload.
3. Resolves the GitHub username to a Frappe User via **Frappe Agile Settings → Development Team** (matched by `github_username`).
4. Sets `pr_reviewer_user` on the Work Item (if not already set).
5. The **"Work Item - PR Reviewer" Assignment Rule** then auto-assigns the Work Item to the reviewer when it enters "Pending Review".

> **Note:** If the GitHub reviewer cannot be mapped to a Frappe User, a warning is logged to Error Log but the workflow transition still proceeds.

**Example payload (PR opened with reviewer):**
```json
{
  "action": "opened",
  "pull_request": {
    "html_url": "https://github.com/org/repo/pull/42",
    "merged": false,
    "title": "Fix login bug",
    "body": "Closes WI-000007. Added null check on session.",
    "head": { "ref": "feature/WI-000007-fix-login" },
    "requested_reviewers": [
      { "login": "octocat" }
    ]
  }
}
```

---

### GitHub Username Mapping (Required for PR Reviewer)

To enable automatic `pr_reviewer_user` population, each developer's GitHub username must
be configured in **Frappe Agile Settings → Development Team**:

| User | GitHub Username |
|---|---|
| `alice@one-fm.com` | `alice-gh` |
| `bob@one-fm.com` | `bob-dev` |

The webhook performs a **case-insensitive** lookup of the GitHub login against this table.
If no match is found, `pr_reviewer_user` is left empty and a warning is logged.

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

**For `pull_request` and `pull_request_review` events:**
1. **PR body** — e.g., `Closes WI-000042` or `Linked to WI-42`
2. **PR title** — e.g., `[WI-42] Fix login`
3. **Branch name** — e.g., `feature/WI-000042-add-auth`

**For `push` events:**
1. **Commit messages** (concatenated) — e.g., `fix(WI-000042): correct logic`
2. **Branch name** — e.g., `feature/WI-000042-add-auth`

If no Work Item ID is found in a push event, it is **silently ignored** (no error logged — not every push references a WI). For PR events, a missing ID is logged to Error Log.

---

## How to Reference a Work Item in a PR

Developers can mention the Work Item **anywhere** — the webhook searches body → title → branch name in priority order. Any of the following formats work:

### ✅ Option 1 — PR Body (recommended)

```
Closes WI-1532189
Linked to WI-1532189
This PR implements WI-1532189
Related: WI-1532189
```

GitHub's `Closes WI-XXXXXX` syntax is recommended — it auto-links the issue in GitHub's UI and is picked up first by the webhook.

### ✅ Option 2 — PR Title

```
[WI-1532189] Fix null check on session login
WI-1532189: Add leave validation logic
feat(WI-1532189): refactor approval flow
```

### ✅ Option 3 — Branch Name (fallback)

```
feature/WI-1532189-fix-login
WI-1532189/add-validation
bugfix/WI-1532189
```

### Rules

- **Case-insensitive** — `wi-1532189` and `WI-1532189` both work
- **No leading zeros required** — `WI-42` and `WI-000042` are both valid
- **First match wins** — body is checked before title, title before branch name
- **Multiple WIs** — only the first match found is acted upon

### Team Convention

Enforce branch naming like `feature/WI-XXXXXXX-short-description` so the webhook always has a fallback even if the PR body is missing a reference. This also makes it easy to identify which Work Item a branch belongs to directly from GitHub's branch list.

---


## Error Handling

All errors are recorded in **Frappe Error Log** (desk → `Error Log` DocType):

| Situation | Logged? | HTTP response |
|---|---|---|
| `github_webhook_secret` not in site_config | ✅ logged | 401 thrown |
| Missing/malformed `X-Hub-Signature-256` header | ❌ not logged | 401 thrown |
| Signature mismatch (wrong secret) | ✅ logged (prefix only) | 401 thrown |
| Malformed JSON body | ✅ logged | 400 thrown |
| WI not found in push ref/commits | ✅ logged | 200 ok |
| WI not found in PR body/title/branch | ✅ logged (PR events only) | 200 ok |
| Push with no WI reference | ❌ silently ignored | 200 ok |
| `workflow_state` is None or missing | ✅ logged | 200 ok |
| Invalid transition from current state | ✅ logged with current state | 200 ok |
| Unexpected exception in `_apply` | ✅ logged with traceback | 200 ok |

---

## Local Testing (without GitHub)

You can fully test the webhook locally using `curl` — no GitHub account or tunnel needed.

### Step 1 — Prerequisites

```bash
# 1. Add the secret to site_config (only once)
bench --site onefm set-config github_webhook_secret "test-secret-123"

# 2. Restart to load the new config
bench restart

# 3. Verify bench is reachable
curl -s "http://onefm.localhost:8006/api/method/frappe.ping"
# → {"message":"pong"}
```

### Step 2 — Understand the required Work Item state

Each curl command only works when the Work Item is in the **correct preceding state**.
The webhook never skips steps — it follows the workflow order:

```
Open → In Progress → Pending Action Plan → Pending Execution
                                                  │
                                           [push curl] ↓
                                             Pending PR
                                                  │
                                        [PR opened curl] ↓
                                           Pending Review
                                            /           \
                               [review curl] ↓       [PR merged curl] ↓
                               Changes Requested       In Staging
```

Advance the Work Item to the correct state in the desk first (click the workflow action buttons), then run the matching curl.

> **Quick testing shortcut** — force-set state via bench (local only, do not use in production):
> ```bash
> bench --site onefm execute frappe.db.set_value --args '["Work Item","WI-XXXXXX","workflow_state","Pending Execution"]'
> bench --site onefm clear-cache
> ```

---

### Step 3 — Run the curl commands

Replace `WI-XXXXXX` with your actual Work Item name throughout.

#### ⚪ Push → `Pending PR`
*(Work Item must be in `Pending Execution`)*

```bash
SECRET="test-secret-123"
PAYLOAD='{"ref":"refs/heads/feature/WI-XXXXXX-fix","commits":[{"message":"fix: WI-XXXXXX implementation"}]}'
SIG="sha256=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')"
curl -s -X POST "http://onefm.localhost:8006/api/method/frappe_agile.api.github_webhook.handle_github_webhook" \
  -H "Content-Type: application/json" -H "X-GitHub-Event: push" -H "X-Hub-Signature-256: $SIG" \
  -d "$PAYLOAD"
```

#### 🔵 PR Opened → `Pending Review`
*(Work Item must be in `Pending PR`)*

```bash
SECRET="test-secret-123"
PAYLOAD='{"action":"opened","pull_request":{"html_url":"https://github.com/test/repo/pull/1","merged":false,"title":"[WI-XXXXXX] fix","body":"WI-XXXXXX","head":{"ref":"feature/test"}}}'
SIG="sha256=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')"
curl -s -X POST "http://onefm.localhost:8006/api/method/frappe_agile.api.github_webhook.handle_github_webhook" \
  -H "Content-Type: application/json" -H "X-GitHub-Event: pull_request" -H "X-Hub-Signature-256: $SIG" \
  -d "$PAYLOAD"
```

#### 🟡 Review Changes Requested → `Changes Requested`
*(Work Item must be in `Pending Review`)*

```bash
SECRET="test-secret-123"
PAYLOAD='{"review":{"state":"changes_requested"},"pull_request":{"html_url":"https://github.com/test/repo/pull/1","title":"","body":"WI-XXXXXX","head":{"ref":"feature/test"}}}'
SIG="sha256=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')"
curl -s -X POST "http://onefm.localhost:8006/api/method/frappe_agile.api.github_webhook.handle_github_webhook" \
  -H "Content-Type: application/json" -H "X-GitHub-Event: pull_request_review" -H "X-Hub-Signature-256: $SIG" \
  -d "$PAYLOAD"
```

#### 🟢 PR Merged → `In Staging`
*(Work Item must be in `Pending Review`)*

```bash
SECRET="test-secret-123"
PAYLOAD='{"action":"closed","pull_request":{"html_url":"https://github.com/test/repo/pull/1","merged":true,"title":"","body":"WI-XXXXXX","head":{"ref":"feature/test"}}}'
SIG="sha256=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')"
curl -s -X POST "http://onefm.localhost:8006/api/method/frappe_agile.api.github_webhook.handle_github_webhook" \
  -H "Content-Type: application/json" -H "X-GitHub-Event: pull_request" -H "X-Hub-Signature-256: $SIG" \
  -d "$PAYLOAD"
```

**Expected response for all:** `{"message": {"status": "ok"}}`

---

### Step 4 — Verify & Troubleshoot

```bash
# Check current workflow_state of a Work Item
bench --site onefm execute frappe.db.get_value --args '["Work Item","WI-XXXXXX","workflow_state"]'
```

| Symptom | Cause | Fix |
|---|---|---|
| `Expecting value: line 1 column 1` | Bench not running | Run `bench start` |
| `{"status":"ok"}` but state unchanged | WI not in required state | Check state with bench execute above |
| `_server_messages: Not a valid Workflow Action` | Same as above | Advance WI to correct state first |
| `signature mismatch` in Error Log | Secret mismatch | Ensure `site_config.json` secret matches `$SECRET` |

Check **desk → Error Log** and search `GitHub Webhook` for detailed error messages.

---

## Running Tests

```bash
bench --site onefm run-tests --app frappe_agile --module frappe_agile.api.test_github_webhook
```
