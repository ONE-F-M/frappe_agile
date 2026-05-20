# AGENTS.md

This repository hosts the `frappe_agile` custom Frappe app.

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

Keep the subject non-empty, lowercase where practical, and focused on the
single task implemented by the branch.
