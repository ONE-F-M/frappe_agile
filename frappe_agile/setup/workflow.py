from frappe_agile.frappe_agile.custom.workflow.workflow import get_workflow_json_file
from one_fm.custom.workflow.workflow import create_workflow, delete_workflow


def create_workflows():
	create_workflow(get_workflow_json_file("work_item.json"))


def delete_workflows():
	delete_workflow(get_workflow_json_file("work_item.json"))
