import json
import os

import frappe


def get_json_file(file_name, folder):
	"""
	Load and return JSON data from a file in the specified folder.

	Args:
		file_name (str): The name of the JSON file (must end with `.json`).
		folder (str): The absolute path to the folder containing the JSON file.

	Returns:
		dict: Parsed JSON data from the file.
	"""
	if not file_name.endswith(".json"):
		frappe.log_error("Only JSON files are allowed. Please ensure the file ends with '.json'.")
		return {}

	file_path = os.path.join(folder, file_name)

	if not os.path.isfile(file_path):
		frappe.log_error(f"File not found: {file_path}")
		return {}

	try:
		with open(file_path, "r") as f:
			return json.load(f)
	except json.JSONDecodeError as e:
		frappe.log_error(title=f"Invalid JSON format in file {file_path}", message=str(e))
	except Exception as e:
		frappe.log_error(title=f"An error occurred while reading the file {file_path}", message=str(e))

	return {}


def get_workflow_json_file(file_name):
	"""Load workflow JSON from frappe_agile's workflow folder."""
	folder = frappe.get_app_path("frappe_agile", "frappe_agile", "custom", "workflow")
	return get_json_file(file_name, folder)


def create_workflow(workflow: dict):
	"""
	Create or update a Workflow along with its states and actions.

	Args:
		workflow (dict): A dictionary representing the workflow data.
	"""
	if not isinstance(workflow, dict) or not ("states" in workflow and "transitions" in workflow):
		frappe.log_error(title="Invalid or incomplete workflow definition.")
		return

	try:
		state_values = [{"workflow_state_name": state["state"], "style": state.get("style")} for state in workflow["states"]]
		create_workflow_state(state_values)

		actions = list(set([transition["action"] for transition in workflow["transitions"]]))
		create_workflow_action_master(actions)

		if not frappe.db.exists("Workflow", workflow["workflow_name"]):
			frappe.get_doc(workflow).insert(ignore_permissions=True)
		else:
			workflow_obj = frappe.get_doc("Workflow", workflow["workflow_name"])
			workflow_obj.update(workflow)
			workflow_obj.save(ignore_permissions=True)
	except Exception as e:
		frappe.log_error(
			title="Workflow Creation Error",
			message=f"Failed to create or update workflow '{workflow.get('workflow_name', '')}':\n{frappe.get_traceback()}"
		)


def create_workflow_state(states: list):
	"""
	Create or update Workflow States.

	Args:
		states (list[dict]): A list of state dictionaries with workflow_state_name and optional style.
	"""
	for state in states:
		try:
			if not frappe.db.exists("Workflow State", state["workflow_state_name"]):
				frappe.get_doc({"doctype": "Workflow State", **state}).insert(ignore_permissions=True)
			else:
				existing = frappe.get_doc("Workflow State", state["workflow_state_name"])
				if state.get("style") and existing.style != state.get("style"):
					existing.style = state["style"]
					existing.save(ignore_permissions=True)
		except Exception as e:
			frappe.log_error(
				title="Workflow State Error",
				message=f"Failed to create/update state '{state.get('workflow_state_name')}':\n{frappe.get_traceback()}"
			)


def create_workflow_action_master(action_masters):
	"""
	Create Workflow Action Masters if they don't already exist.

	Args:
		action_masters (str or list[str]): Action(s) to be created if not already present.
	"""
	if isinstance(action_masters, str):
		action_masters = [action_masters]

	if not isinstance(action_masters, list):
		frappe.log_error(title="Workflow actions must be a list or string.")
		return

	action_masters = list(set([a.strip() for a in action_masters if isinstance(a, str) and a.strip()]))

	if not action_masters:
		return

	try:
		existing_actions = frappe.get_all(
			"Workflow Action Master",
			filters={"workflow_action_name": ["in", action_masters]},
			pluck="workflow_action_name"
		)

		to_create = set(action_masters) - set(existing_actions)

		for action in to_create:
			frappe.get_doc({
				"doctype": "Workflow Action Master",
				"workflow_action_name": action
			}).insert(ignore_permissions=True)

	except Exception as e:
		frappe.log_error(
			title="Workflow Action Master Error",
			message=f"Error while creating workflow actions:\n{frappe.get_traceback()}"
		)


def delete_workflow(workflow: dict):
	"""
	Delete a Workflow by name.

	Args:
		workflow (dict): A dictionary with workflow_name key.
	"""
	name = workflow.get("workflow_name")
	if not name:
		frappe.log_error(title="Missing 'workflow_name' in workflow deletion input.")
		return

	try:
		if frappe.db.exists("Workflow", name):
			frappe.delete_doc("Workflow", name, ignore_permissions=True)
	except Exception as e:
		frappe.log_error(
			title="Workflow Deletion Error",
			message=f"Failed to delete workflow '{name}':\n{frappe.get_traceback()}"
		)
