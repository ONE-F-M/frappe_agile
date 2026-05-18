# AGENTS.md

This repository hosts the `frappe_agile` custom Frappe app for sprint and task management inside the ONE-FM ecosystem.

This file is written for coding agents and automation tools that need to read, update, test, or extend the app safely. Treat it as the first operational guide before touching doctypes, workflows, sprint data, or webhook logic.

## Stack

- Frappe v15
- Python 3.10+
- MariaDB
- Redis
- Bench-managed development workflow
- GitHub PR based deployment flow

## Purpose of the App

`frappe_agile` is the planning and delivery layer used to manage sprint work across teams. It is not just a generic issue tracker. It encodes a specific work model used by the team:

- work is captured as Work Items
- work is grouped into Sprints
- work is reviewed through explicit reviewer and PR fields
- sprint status affects how work can move
- automation and agent workflows depend on the integrity of this data

Because agents read from this app to decide what to work on, data quality matters. A sloppy change here can break both human planning and downstream automation.

## Core Agile Data Model

### Board → Column → Task relationship

The planning model assumes work is visible on boards and moves through columns over time.

- **Board**: container for a planning view
- **Column**: status lane or workflow stage on a board
- **Task / Work Item**: the unit of execution displayed inside a board column

Even when a board document is not the immediate object being edited, preserve this mental model. UI and reporting layers expect work to be representable on boards and sortable by state.

### Sprint → Task assignment

A Sprint is a time-boxed collection of work.

A Sprint contains:
- a naming prefix
- start and end dates
- a status (`Draft`, `Active`, `Completed`)
- optional project linkage
- expected velocity / target point metrics
- a child table of linked work items

A Work Item can be assigned to a Sprint. When that happens:
- the Sprint child table should stay in sync
- sprint velocity should reflect story points of assigned work items
- sprint status may restrict work item updates
- sprint completion should freeze historical planning metrics

### Epic → User Story → Task hierarchy

Work is structured hierarchically:

- **Epic**: large container for a body of work
- **User Story**: a user-facing slice of value within an Epic
- **Task**: execution-level work needed to deliver a story
- **Bug**: defect work tracked in the same ecosystem

Important expectations:
- Epics are containers, not execution items
- story points belong to executable work items, not Epics
- User Stories and Tasks may belong to a Sprint
- hierarchy should remain readable for agents and humans alike

## Work Item conventions

The `Work Item` doctype is the most important doctype in the app.

Common fields include:
- naming series / generated WI number
- work item type
- title
- priority
- project
- sprint
- sprint status
- story points
- PR link
- PR reviewer user
- AI tooling feedback
- labels
- rejection notes

### Work Item types

Supported types:
- Epic
- User Story
- Task
- Bug

### Story point rules

Agents must respect these rules:
- Epics should not carry story points
- sprint velocity depends on story points from linked work items
- changing a work item sprint should trigger sprint recalculation logic
- assigning work to a completed sprint is invalid

### User Story acceptance criteria format

When acceptance criteria exist in a Work Item description, keep them explicit, testable, and implementation-neutral when possible.

Good acceptance criteria:
- define observable outcomes
- describe required fields, workflows, or reports
- specify constraints like branch names, CI checks, or file paths
- avoid vague terms like “improve” or “make better” without measurable detail

If you are generating or editing Work Item descriptions, prefer:
- numbered steps
- explicit file paths
- exact workflow names
- clear acceptance criteria bullets

## Sprint lifecycle and status transitions

Sprint lifecycle is central to the app.

Primary states:
- **Draft**
- **Active**
- **Completed**

### Expected behavior

#### Draft
- initial planning state
- work can be assigned and adjusted
- sprint dates and goals may still be refined

#### Active
- sprint is in execution
- only one active sprint per prefix should exist at a time
- work items assigned here contribute to expected velocity

#### Completed
- sprint is closed
- completed status must not be reverted casually
- completed sprint velocity should be preserved as a historical record
- linked work items should not continue to mutate as though the sprint were active

### Completion handling

When a sprint is completed, incomplete items may need one of these outcomes:
- move to backlog
- move to a newly created sprint
- remain historically attached depending on workflow rules

If code touches sprint completion logic, verify:
- child table sync remains correct
- expected velocity is frozen when intended
- incomplete work handling matches actual business rules

## Sprint metrics

The app tracks planning metrics that agents should preserve.

### Expected velocity

Expected velocity is derived from linked work item story points.

Agents must not blindly overwrite it. Respect the controller logic around:
- recalculation on assignment changes
- freezing values for completed sprints
- preserving history during closure flows

### Target points

Target points may represent intended sprint scope. Do not assume they equal actual velocity.

### Burndown / remaining scope

Even where explicit burndown documents are absent, remaining scope can often be derived from:
- assigned story points
- completion state of work items
- sprint child table rows

If implementing reports or tests, prefer deriving from real sprint/work item relationships instead of hardcoded math.

## API patterns for programmatic access

This app is used by automation, so API discipline matters.

### General patterns

Prefer:
- Frappe controller methods for business logic
- whitelisted methods where external invocation is intended
- doc events for synchronization logic
- query builder for aggregate calculations when appropriate

Avoid:
- duplicating controller logic in scripts
- direct SQL writes unless truly necessary
- bypassing validation without a strong reason

### Programmatic reads

Safe patterns usually include:
- `frappe.get_doc()` for document-level logic
- `frappe.get_all()` / `frappe.get_list()` for filtered lists
- `frappe.db.get_value()` for single-field lookups
- query builder for sums like story point totals

### Programmatic writes

Prefer:
- insert / save on real documents
- child table updates through document APIs
- using existing hooks to trigger recalculation and sync behavior

Be careful with:
- `db_set` when business logic should run
- direct deletes on child rows without understanding sync implications
- modifying completed sprint data

## Important implementation areas

Agents working in this repo should inspect these areas before making non-trivial changes:

- `frappe_agile/frappe_agile/doctype/sprint/`
- `frappe_agile/frappe_agile/doctype/work_item/`
- `frappe_agile/frappe_agile/doctype/sprint_work_item/`
- `frappe_agile/api/`
- `hooks.py`
- GitHub workflow files under `.github/workflows/`

### Sprint controller

The Sprint controller is responsible for:
- naming behavior
- active sprint uniqueness
- status transition validation
- expected velocity calculation
- syncing sprint status back to linked work items
- incomplete item handling during closeout flows

### Work Item controller

The Work Item controller is responsible for:
- sprint assignment rules
- work item child-table sync into the Sprint
- project compatibility checks
- story point restrictions
- preventing invalid updates against completed sprints

### Webhook / integration layer

The GitHub webhook integration should be treated as an integration boundary.

When editing it:
- preserve signature verification behavior
- keep event-to-message mapping explicit
- do not silently widen trust boundaries
- prefer well-scoped helpers with direct tests

## Deployment workflow

Branch flow is explicit and should be respected:

1. `staging`
2. `test-production`
3. `version-15`

### Expected movement

- open work branches off the appropriate source branch
- open PRs back into `staging` unless instructed otherwise
- promote tested changes forward through the protected branch chain
- do not push directly to protected branches

### CI expectations

Changes may be gated by:
- server tests
- linter workflows
- semantic commit checks
- dependency scanning
- repository policy checks

If a work item explicitly mentions CI alignment with upstream Frappe, match the requested versions and workflow structure closely instead of approximating.

## Security constraints

### Board visibility

**Never modify board visibility without a permission check.**

This is a hard rule. If code touches visibility, sharing, filters, or board exposure:
- confirm permission enforcement exists
- preserve role boundaries
- avoid accidental widening of access

### Sprint and work item data

Treat sprint data as operational team data:
- visible to intended internal roles
- not automatically public
- not safe to expose through unauthenticated APIs

### Webhooks and external input

For inbound webhooks or external calls:
- verify signatures when configured
- validate payload shape
- fail closed on malformed auth
- log enough for debugging without leaking secrets

### PR fields and reviewer fields

PR links, PR reviewers, and AI tooling feedback may affect downstream automation.
Do not casually rename or repurpose these fields without updating the consumers.

## Testing guidance

Run targeted tests when possible.

Examples:
```bash
bench --site <site> run-tests --app frappe_agile --failfast
bench --site <site> run-tests --app frappe_agile --module frappe_agile.frappe_agile.doctype.sprint.test_sprint
bench --site <site> run-tests --app frappe_agile --module frappe_agile.api.test_github_webhook
```

### Test writing rules

When writing tests for this repo:
- prefer `FrappeTestCase` for doctype logic
- create actual documents instead of fake dict-only tests when business logic is document-driven
- clean up test data explicitly if commits happen inside business logic
- avoid brittle assumptions about autoname counters unless necessary
- test lifecycle transitions, not just field assignment

## How a Symphony-style agent should read from this app

A Symphony-style agent or similar coding agent should use this app as a source of truth for work planning.

Recommended approach:
1. read Work Items assigned or targeted for execution
2. inspect story points, sprint, reviewer, PR requirements, and labels
3. read description and acceptance criteria carefully
4. preserve hierarchy context (Epic → User Story → Task)
5. keep PR links and reviewer fields updated if the workflow requires it

The agent should not:
- invent acceptance criteria not present in the Work Item without marking them clearly
- silently change planning metadata to make implementation easier
- assume completed sprints are editable planning spaces

## Practical guardrails for coding agents

Before changing code:
- identify the doctype or workflow owner logic first
- search hooks before adding duplicate triggers
- check whether a field is fetched, mirrored, or computed elsewhere
- verify whether a reported bug is actually business logic, test drift, or CI config drift

Before changing data:
- confirm whether the sprint is active or completed
- confirm project compatibility rules
- confirm whether child tables are supposed to be read-only reflections

Before shipping:
- compare the branch against the work item description exactly
- make sure file paths, versions, and CI job names match if the task is explicit
- avoid “close enough” when the work item is specification-heavy

## Summary

`frappe_agile` is not just a CRUD app. It is a planning system, a workflow carrier, and an input source for downstream agents.

Work carefully.
Preserve lifecycle rules.
Respect sprint history.
Keep CI and branch behavior explicit.
And never loosen board visibility or workflow constraints without understanding the impact.
