# AGENTS.md — frappe_agile

This repository hosts the `frappe_agile` custom Frappe app for agile project management — sprints, boards, backlogs, and work item tracking natively integrated with Frappe/ERPNext.

## Stack

- Frappe v15
- Python 3.10+
- Node.js 18+
- MariaDB 10.6+
- Redis 6.x+ (caching and background jobs)

## Repository Layout

```
frappe_agile/
├── frappe_agile/
│   ├── api/                          # Whitelisted API endpoints
│   │   ├── github_webhook.py         # GitHub webhook handler (allow_guest)
│   │   └── test_github_webhook.py    # Webhook tests
│   ├── frappe_agile/
│   │   ├── doctype/                  # All DocTypes
│   │   │   ├── frappe_agile_settings/  # App-level settings (Single)
│   │   │   ├── sprint/               # Sprint DocType (core)
│   │   │   ├── sprint_work_item/     # Child table linking sprints to work items
│   │   │   ├── work_item/            # Work Item DocType (task/story/epic)
│   │   │   ├── work_item_label/      # Child table for labels
│   │   │   ├── work_item_template/   # Templates for work items
│   │   │   ├── label/                # Label DocType
│   │   │   ├── development_team_member/  # Team member child table
│   │   │   └── rejection_details/    # Rejection details child table
│   │   ├── report/                   # Script Reports
│   │   │   ├── sprint_report/
│   │   │   ├── sprint_report_per_business_analyst/
│   │   │   ├── sprint_report_per_developer/
│   │   │   ├── sprint_summary/
│   │   │   ├── sprint_summary_(party)/
│   │   │   ├── sprint_summary_report/
│   │   │   └── ai_usage_report/
│   │   ├── page/                     # Desk pages
│   │   └── workspace/                # Workspace definitions
│   ├── hooks.py                      # App hooks (doc_events, scheduler, etc.)
│   ├── patches/                      # Data migration patches
│   ├── patches.txt                   # Patch registry
│   ├── tests/                        # App-level tests
│   │   └── test_sprint_lifecycle.py  # Sprint lifecycle tests (10 cases)
│   ├── public/                       # Static assets (JS/CSS)
│   └── templates/                    # Jinja templates
├── .github/workflows/
│   ├── server-tests.yml              # Server tests CI (3 protected branches)
│   └── linters.yml                   # 4-job linter CI
├── .pre-commit-config.yaml           # Frappe-aligned pre-commit hooks
├── commitlint.config.js              # Conventional commit enforcement
├── pyproject.toml                    # Build config, Ruff, mypy, coverage
├── AGENTS.md                         # This file
└── README.md                         # User-facing documentation
```

## Agile Data Model

### Core Entities

```
Epic (Work Item, type="Epic")
  └── User Story (Work Item, type="User Story")
        └── Task (Work Item, type="Task")
              └── Sub-Task (Work Item, type="Sub-Task")
```

- **Work Item** — The central DocType. Every epic, user story, task, and sub-task is a Work Item with a `work_item_type` field. Work Items have:
  - `title`, `description`, `priority` (Critical/High/Medium/Low)
  - `status` (Open/In Progress/In Review/Completed/Closed/Blocked)
  - `story_points` — numeric effort estimate
  - `assignee_user` — Link to User
  - `sprint` — Link to Sprint (via Sprint Work Item child table)
  - `epic` — Link to parent Epic Work Item
  - `labels` — child table of Label links

- **Sprint** — Time-boxed iteration with:
  - `sprint_name`, `start_date`, `end_date`
  - `status` — Draft → Active → Completed
  - `sprint_work_items` — child table of Sprint Work Item entries
  - Velocity fields: `expected_velocity`, `accepted_points`, `brought_forward_points`
  - `handle_incomplete_items` — flag for sprint close behavior

- **Frappe Agile Settings** — Single DocType for app-level configuration

### Key Relationships

```
Sprint ──(has many)──> Sprint Work Item ──(links to)──> Work Item
Work Item ──(parent_work_item)──> Work Item  (self-referential hierarchy)
Work Item ──(epic)──> Work Item  (epic link)
Work Item ──(has many)──> Work Item Label ──(links to)──> Label
```

## Sprint Lifecycle

### Status Transitions

```
Draft ──(start)──> Active ──(complete)──> Completed
```

**Rules:**
- Only one sprint can be `Active` at a time (enforced by `validate_active_sprint_uniqueness`)
- Status transitions are validated — cannot skip states
- When a sprint completes:
  - Incomplete items are handled based on `handle_incomplete_items` flag
  - A new sprint can be auto-created with carried-forward items
  - Velocity is recalculated (`_recalculate_sprint_velocity`)
  - Brought-forward points are computed (`_recalculate_brought_forward`)
  - Accepted points are finalized (`_recalculate_accepted_points`)

### Story Point Tracking

- `expected_velocity` — calculated from assigned story points
- `accepted_points` — sum of completed work item story points
- `brought_forward_points` — points carried from a previous sprint

## API Patterns

### Whitelisted Endpoints

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `frappe_agile.api.github_webhook.handle_github_webhook` | POST | Guest (HMAC verified) | Receives GitHub webhook events and maps them to BPMN messages |
| `frappe_agile.frappe_agile.doctype.sprint.sprint.get_or_create_target_sprint` | POST | Authenticated | Gets or creates a sprint for carrying forward items |
| `frappe_agile.frappe_agile.doctype.sprint.sprint.handle_incomplete_items` | POST | Authenticated | Handles incomplete items at sprint close (carry forward or close) |

### GitHub Webhook Integration

The webhook handler (`github_webhook.py`):
1. Verifies HMAC signature using a stored secret
2. Extracts Work Item ID from PR titles/branch names (pattern: `WI-XXXXXX`)
3. Maps GitHub events to BPMN message names (e.g., `pr_opened`, `pr_merged`, `review_approved`)
4. Delivers messages to the BPMN engine via `_deliver_bpmn_message`

### Doc Events (hooks.py)

Sprint velocity is recalculated automatically via `doc_events` hooks on Work Item:
- `on_update` → `update_sprint_velocity`
- `validate` → `validate_work_item_sprint`

## Testing

### Running Tests

```bash
bench run-tests --app frappe_agile --failfast
```

### Test Structure

- `frappe_agile/tests/test_sprint_lifecycle.py` — 10 test cases covering:
  - Sprint creation with dates
  - Draft → Active → Completed transitions
  - Task assignment to sprints
  - Story point tracking
  - Sprint velocity calculation
  - Burndown data generation
- `frappe_agile/api/test_github_webhook.py` — GitHub webhook handler tests

### Coverage

Coverage is configured in `pyproject.toml`:
- Threshold: 30% minimum (enforced via `--cov-fail-under=30`)
- Source: `frappe_agile` package
- Excluded: tests, patches, hooks, config

## Branch and PR Workflow

### Protected Branches

| Branch | Purpose |
|---|---|
| `staging` | Integration branch — all PRs target here first |
| `test-production` | Pre-production testing |
| `version-15` | Production release branch |

### PR Flow

```
feature/WI-XXXXXX ──(PR)──> staging ──(PR)──> test-production ──(PR)──> version-15
```

### Commit Convention

All commits must follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>
```

Allowed types: `build`, `chore`, `ci`, `deprecate`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style`, `test`

### CI Checks (Must Pass Before Merge)

1. **Server Tests** (`server-tests.yml`) — runs `bench run-tests --app frappe_agile --failfast`
2. **Linters** (`linters.yml`) — 4 jobs:
   - `commit-lint` — enforces conventional commits
   - `linter` — Semgrep security rules
   - `precommit` — runs all pre-commit hooks
   - `deps-vulnerable-check` — pip-audit for vulnerable dependencies

## Security Constraints

- **Never modify board visibility without a permission check**
- Treat sprint data as team-visible but access-controlled
- Validate user roles before exposing sprint or board details
- The GitHub webhook endpoint uses `allow_guest=True` but validates HMAC signatures
- All other whitelisted methods require authenticated users
- Use `frappe.get_list()` (permission-aware) in user-facing code, not `frappe.get_all()`

## Reports

| Report | Description |
|---|---|
| Sprint Report | Per-sprint work item breakdown |
| Sprint Report per Business Analyst | Sprint metrics grouped by BA |
| Sprint Report per Developer | Sprint metrics grouped by developer |
| Sprint Summary | Aggregate sprint statistics |
| Sprint Summary (Party) | Sprint summary by party (configurable velocity) |
| Sprint Summary Report | Overall sprint summary |
| AI Usage Report | AI tools usage tracking |
