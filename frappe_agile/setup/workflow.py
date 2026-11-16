from frappe_agile.frappe_agile.custom.workflow.workflow import (
	create_workflow,
	create_workflow_state,
	delete_workflow,
	get_workflow_json_file,
)

# Status options of Work Item that have no state in the (inactive) Work Item workflow. The Workflow State record has to exist because
# before_save only copies a status into workflow_state when a Workflow State of that name exists.
EXTRA_WORK_ITEM_STATES = [{"workflow_state_name": "In Testing", "style": "Info"}]


def create_workflows():
	create_workflow(get_workflow_json_file("work_item.json"))
	create_workflow_state(EXTRA_WORK_ITEM_STATES)


def delete_workflows():
	delete_workflow(get_workflow_json_file("work_item.json"))
