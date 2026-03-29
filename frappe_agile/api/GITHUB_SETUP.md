# GitHub Webhook — Production Setup Guide

Step-by-step guide to connect your GitHub Organisation to the `frappe_agile` webhook endpoint.

---

## Prerequisites

- `frappe_agile` app installed and migrated on the target site
- Site accessible over **HTTPS** (required for GitHub webhook delivery)
- GitHub Organisation admin access

---

## Step 1 — Generate a Strong Secret

Run this on the server (or locally) to generate a cryptographically secure secret:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
# Example output: a3f9c2e1b4d7...
```

> ⚠️ **Never commit this secret to Git.** Store it only in `site_config.json`.

---

## Step 2 — Add Secret to Frappe Site Config

```bash
bench --site <your-site> set-config github_webhook_secret "your-generated-secret-here"
bench restart
```

**For staging.one-fm.com specifically:**
```bash
bench --site staging.one-fm.com set-config github_webhook_secret "your-generated-secret-here"
bench restart
```

**Verify the site is reachable:**
```bash
curl -s "https://staging.one-fm.com/api/method/frappe.ping"
# Expected: {"message":"pong"}
```

---

## Step 3 — Configure GitHub Organisation Webhook

1. Go to: **GitHub → Your Organisation → Settings → Webhooks → Add webhook**

2. Fill in the fields:

   | Field | Value |
   |---|---|
   | **Payload URL** | `https://staging.one-fm.com/api/method/frappe_agile.api.github_webhook.handle_github_webhook` |
   | **Content type** | `application/json` |
   | **Secret** | Same value set in Step 2 |
   | **SSL verification** | ✅ Enable SSL verification |
   | **Which events?** | Select **"Let me select individual events"** |

3. Check these events only:

   - ☑ **Pull requests**
   - ☑ **Pull request reviews**
   - ☑ **Pushes**

4. Ensure **Active** is checked, then click **Add webhook**.

GitHub immediately sends a `ping` event — a ✅ green tick next to the webhook means the connection succeeded.

---

## Step 4 — Verify the Connection

### On GitHub
Go to **Org → Settings → Webhooks → your webhook → Recent Deliveries**

The `ping` delivery should show:
- **Response:** `200`
- **Body:** `{"message": {"status": "ok"}}`

### On Frappe
Check for any errors in the Error Log:

```bash
bench --site staging.one-fm.com execute frappe.db.get_all \
  --args '["Error Log"]' \
  --kwargs '{"filters":[["title","like","GitHub Webhook%"]],"fields":["name","title","creation"],"limit":5}'
```

No results = no errors. ✅

---

## Step 5 — Ensure Workflow is Active on the Site

```bash
# Check if workflow exists
bench --site staging.one-fm.com execute frappe.db.exists --args '["Workflow","Work Item"]'

# If it returns null, install it:
bench --site staging.one-fm.com execute frappe_agile.setup.workflow.create_workflows
```

---

## Security Checklist

| Item | Action |
|---|---|
| Secret is 32+ random hex chars | ✅ Use `secrets.token_hex(32)` |
| Secret not in version control | ✅ Only in `site_config.json` |
| Site uses HTTPS | ✅ `staging.one-fm.com` |
| SSL verification enabled in GitHub | ✅ Required for HTTPS sites |
| `frappe_agile` installed on site | Verify with `bench --site <site> list-apps` |
| Workflow active | Verify with `frappe.db.exists` above |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| GitHub shows ❌ on ping delivery | Site unreachable or wrong URL | Verify URL with `curl` |
| `401` response from GitHub | Secret mismatch | Re-check `site_config.json` value matches GitHub secret field |
| `Webhook secret not configured` in Error Log | Secret missing from site_config | Run `bench set-config` and `bench restart` |
| Webhook fires but WI doesn't change state | WI in wrong workflow state | Check state with `frappe.db.get_value` |
| No event in Recent Deliveries | Wrong events selected | Re-check Pull requests, Reviews, Pushes are ticked |

---

## Payload URL Reference

```
https://<your-site>/api/method/frappe_agile.api.github_webhook.handle_github_webhook
```

| Environment | Full URL |
|---|---|
| Staging | `https://staging.one-fm.com/api/method/frappe_agile.api.github_webhook.handle_github_webhook` |
| Production | `https://<production-domain>/api/method/frappe_agile.api.github_webhook.handle_github_webhook` |

---

*For local development testing without GitHub, see [README.md](./README.md#local-testing-without-github).*
