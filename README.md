# Frappe Agile

> Agile project management for Frappe — sprints, boards, and backlogs, natively integrated with your Frappe/ERPNext instance.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | ≥ 3.10 |
| Node.js | ≥ 18 |
| [Frappe Bench](https://github.com/frappe/bench) | ≥ 5.x |
| Frappe Framework | v15 |

Make sure you have a working Frappe bench set up before proceeding. Refer to the [Frappe installation guide](https://frappeframework.com/docs/user/en/installation) if needed.

---

## Installation

### Option 1 — Using `bench get-app` (Recommended)

```bash
cd /path/to/your/bench
bench get-app https://github.com/ONE-F-M/frappe_agile.git --branch develop
bench --site your-site.localhost install-app frappe_agile
```

### Option 2 — Manual Git Clone

```bash
cd /path/to/your/bench/apps
git clone https://github.com/ONE-F-M/frappe_agile.git
cd /path/to/your/bench
bench --site your-site.localhost install-app frappe_agile
```

### Option 3 — Development Setup (for contributors)

```bash
# 1. Clone the repo into your bench apps folder
cd /path/to/your/bench/apps
git clone https://github.com/ONE-F-M/frappe_agile.git
cd frappe_agile

# 2. Install Python package in editable mode
pip install -e .

# 3. Install the app on your site
cd /path/to/your/bench
bench --site your-site.localhost install-app frappe_agile

# 4. Run migrations
bench --site your-site.localhost migrate

# 5. Start the development server
bench start
```

---

## Database Migration

`bench migrate` is the primary command for applying schema changes, patches, and DocType updates. It is **safe to run multiple times** — Frappe tracks which patches have already been applied.

### When to Run

Run `bench migrate` after:
- Installing or upgrading `frappe_agile`
- Pulling new commits that include DocType or patch changes
- Adding/modifying any field definitions in the codebase

### Basic Usage

```bash
bench --site your-site.localhost migrate
```

### Useful Flags

| Flag | Description |
|---|---|
| `--skip-failing` | Skip patches that throw errors (useful during debugging) |
| `--dry-run` | Preview what will run without applying changes |
| `--reset-permissions` | Resets role/permission rules to app defaults |

```bash
# Dry run — see what will be applied without executing
bench --site your-site.localhost migrate --dry-run

# Skip failing patches and continue
bench --site your-site.localhost migrate --skip-failing
```

### How It Works

`bench migrate` performs the following in order:

1. **Syncs DocTypes** — Creates or alters database tables to match JSON definitions
2. **Runs patches** — Executes Python scripts listed in `frappe_agile/patches.txt` (skips already-applied ones)
3. **Rebuilds search index** — Updates global search
4. **Syncs roles & permissions** — Resets to app-defined defaults

### Patch Files

Custom data migration scripts live in:

```
frappe_agile/patches/
    ├── v1_0/
    │   └── your_patch_name.py   ← each patch has an execute() function
```

And are registered in `frappe_agile/patches.txt`:

```
frappe_agile.patches.v1_0.your_patch_name
```

### Troubleshooting

**Schema conflict / column already exists:**
```bash
bench --site your-site.localhost migrate --skip-failing
```

**Patch already ran but needs re-execution:**
```bash
# Remove the patch record from the database, then re-run
bench --site your-site.localhost execute frappe.core.doctype.patch_log.patch_log.delete_patch_log --args "frappe_agile.patches.v1_0.your_patch_name"
bench --site your-site.localhost migrate
```

**After any migration, clear the cache:**
```bash
bench --site your-site.localhost clear-cache
bench --site your-site.localhost clear-website-cache
```

---

## Upgrading

```bash
cd /path/to/your/bench
bench update --pull
bench --site your-site.localhost migrate
```

---

## Uninstalling

```bash
bench --site your-site.localhost uninstall-app frappe_agile
```

---

## Contributing

Contributions are welcome! Please follow the steps below to set up your development environment.

### 1. Fork & Clone

```bash
git clone https://github.com/ONE-F-M/frappe_agile.git
cd frappe_agile
git checkout -b feature/your-feature-name
```

### 2. Install Pre-commit Hooks

This app uses [`pre-commit`](https://pre-commit.com/) for code formatting and linting.

```bash
pip install pre-commit
pre-commit install
```

Pre-commit runs the following tools automatically on every commit:

| Tool | Purpose |
|---|---|
| `ruff` | Python linting & formatting |
| `pyupgrade` | Modernize Python syntax |
| `eslint` | JavaScript linting |
| `prettier` | JS/CSS/JSON formatting |

### 3. Run Tests

```bash
cd /path/to/your/bench
bench --site your-site.localhost run-tests --app frappe_agile
```

### 4. Submit a Pull Request

Push your branch and open a PR against the `develop` branch on GitHub.

---

## License

[MIT](license.txt) — © One FM
