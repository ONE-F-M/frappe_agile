import frappe
from one_fm.utils import get_json_file


def get_workflow_json_file(file_name):
	"""Load workflow JSON from frappe_agile's workflow folder."""
	folder = frappe.get_app_path("frappe_agile", "frappe_agile", "custom", "workflow")
	return get_json_file(file_name, folder)
