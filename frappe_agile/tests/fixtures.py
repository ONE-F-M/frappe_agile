"""Shared test fixtures for frappe_agile.

Sprint.project is mandatory and Sprint.sprint_prefix is read-only, fetched from
`project.custom_sprint_prefix`. A test therefore cannot conjure a sprint from a
bare prefix string any more — it needs a Project that owns that prefix.

`ensure_test_project` gives each test prefix a dedicated Project, so the
existing "test data is anything with prefix TEST/ALPHA/BETA" convention keeps
working: the fetched prefix comes out equal to the requested one.
"""

import frappe

# Prefixes used by tests — any Sprint / Work Item carrying one is test data.
TEST_PREFIXES = ["TEST", "ALPHA", "BETA"]


def test_project_name(prefix):
    """Deterministic Project name for a test prefix."""
    return f"_Test Agile Project {prefix}"


def ensure_test_project(prefix):
    """Return a Project whose custom_sprint_prefix is *prefix*, creating it once.

    Idempotent, and repairs the prefix if a previous run left it wrong — a
    Sprint whose project has the wrong prefix would fetch the wrong value and
    escape the prefix-based cleanup.
    """
    name = test_project_name(prefix)

    if not frappe.db.exists("Project", name):
        frappe.get_doc(
            {
                "doctype": "Project",
                "project_name": name,
                "status": "Open",
                "custom_sprint_prefix": prefix,
            }
        ).insert(ignore_permissions=True)
    elif frappe.db.get_value("Project", name, "custom_sprint_prefix") != prefix:
        frappe.db.set_value("Project", name, "custom_sprint_prefix", prefix, update_modified=False)

    return name


def test_project_names():
    return [test_project_name(p) for p in TEST_PREFIXES]


def delete_test_work_items(extra_projects=None):
    """Delete Work Items belonging to the test Projects.

    Cleaning up by Project rather than by title pattern is what makes this
    complete. `handle_incomplete_items` moves items to the Backlog (sprint = "")
    and commits unconditionally, so those rows survive both the rollback and any
    cleanup that finds work items via their sprint — but they keep the Project
    fetched from the sprint they came from, which still identifies them.
    """
    projects = test_project_names() + list(extra_projects or [])
    frappe.db.delete("Work Item", {"project": ("in", projects)})


def delete_test_projects(extra_projects=None):
    """Remove the Projects created by ensure_test_project.

    Call after the Sprints and Work Items referencing them are gone, otherwise
    those rows are left holding a dangling link.
    """
    delete_test_work_items(extra_projects)
    frappe.db.delete("Project", {"name": ("in", test_project_names() + list(extra_projects or []))})
