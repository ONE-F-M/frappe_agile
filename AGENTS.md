# AGENTS.md

This repository hosts the `frappe_agile` custom Frappe app for sprint and task management.

## Stack
- Frappe v15
- Python 3.10+

## Agile Data Model

Core concepts:
- **Board** -> contains **Columns** -> contains **Tasks**
- **Sprint** -> contains assigned Tasks with start/end dates
- **Epic** -> **User Story** -> **Task** hierarchy
- User Stories carry acceptance criteria

## Sprint Lifecycle

Typical states:
- Draft
- Active
- Completed

Tasks assigned to a sprint should be tracked by story points (assigned, completed, remaining).

## API Patterns

The app exposes Frappe whitelisted endpoints for programmatic access to boards, sprints, and tasks.
Before calling an endpoint, verify the actual function signature in the codebase.

## Testing

Run tests with:
```bash
bench --site <site> run-tests --app frappe_agile --failfast
```

## Branch Workflow

Standard flow:
- `staging`
- `test-production`
- `version-15`

## Commit Format

All commits must use conventional commit titles so the Frappe-aligned
`commitlint.config.js` and pre-commit commit-msg hook can validate them.

Use this format:

```text
<type>(<scope>): <subject>
```

Allowed types are:
- `build`
- `chore`
- `ci`
- `docs`
- `feat`
- `fix`
- `perf`
- `refactor`
- `revert`
- `style`
- `test`

For sprint work, use the work item ID as the scope:

```text
chore(WI-000774): align commitlint with Frappe
```

## Security

- Never modify board visibility without a permission check
- Treat sprint data as team-visible but access-controlled
- Validate user roles before exposing sprint or board details
