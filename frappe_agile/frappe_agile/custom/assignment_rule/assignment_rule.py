import frappe

from frappe_agile.frappe_agile.custom.workflow.workflow import get_json_file


def get_assignment_rule_json_file(file_name):
	"""
	Load JSON data from a file in frappe_agile's assignment_rule folder.

	Args:
		file_name (str): The name of the JSON file (must end with '.json').

	Returns:
		dict: The parsed JSON data.
	"""
	folder = frappe.get_app_path("frappe_agile", "frappe_agile", "custom", "assignment_rule")
	return get_json_file(file_name, folder)


def create_assignment_rule(assignment_rule: dict):
	"""
	Create or update an Assignment Rule based on the provided dictionary.

	Args:
		assignment_rule (dict): A dictionary representing the assignment rule data.
			Must contain a 'name' key.

	Returns:
		None
	"""
	if not assignment_rule or not isinstance(assignment_rule, dict):
		frappe.log_error(title="Invalid assignment rule data.")
		return

	if "name" not in assignment_rule:
		frappe.log_error(title="Missing required field: 'name'.")
		return

	assignment_rule_name = assignment_rule["name"]

	try:
		if not frappe.db.exists("Assignment Rule", assignment_rule_name):
			frappe.get_doc(assignment_rule).insert(ignore_permissions=True)
		else:
			doc = frappe.get_doc("Assignment Rule", assignment_rule_name)
			doc.update(assignment_rule)
			doc.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="Assignment Rule Save Error",
			message=f"Failed to create or update Assignment Rule '{assignment_rule_name}': {frappe.get_traceback()}"
		)


def delete_assignment_rule(assignment_rule: dict):
	"""
	Delete an Assignment Rule based on the 'name' field in the dictionary.

	Args:
		assignment_rule (dict): Dictionary containing at least a 'name' key.

	Returns:
		None
	"""
	if not assignment_rule or not isinstance(assignment_rule, dict):
		frappe.log_error(title="Invalid assignment rule data.")
		return

	name = assignment_rule.get("name")
	if not name:
		frappe.log_error(title="Missing 'name' in assignment rule.")
		return

	try:
		if frappe.db.exists("Assignment Rule", name):
			frappe.delete_doc("Assignment Rule", name, ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="Assignment Rule Deletion Error",
			message=f"Failed to delete Assignment Rule '{name}': {frappe.get_traceback()}"
		)
