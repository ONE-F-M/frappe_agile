import frappe
from frappe_agile.setup.workflow import create_workflows, delete_workflows

REQUIRED_ROLES = ["Business Analyst", "Developer", "Process Owner"]


def create_roles():
	for role_name in REQUIRED_ROLES:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(ignore_permissions=True)


def after_install():
	create_roles()
	create_workflows()


def before_uninstall():
	delete_workflows()
