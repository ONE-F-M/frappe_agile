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


def delete_test_projects():
    """Remove the Projects created by ensure_test_project.

    Call after the Sprints referencing them are gone.
    """
    frappe.db.delete("Project", {"name": ("in", [test_project_name(p) for p in TEST_PREFIXES])})
