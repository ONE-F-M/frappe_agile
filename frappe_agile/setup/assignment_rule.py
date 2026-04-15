from frappe_agile.frappe_agile.custom.assignment_rule.assignment_rule import (
	get_assignment_rule_json_file, create_assignment_rule, delete_assignment_rule
)


def create_assignment_rules():
	create_assignment_rule(get_assignment_rule_json_file("work_item_developer.json"))
	create_assignment_rule(get_assignment_rule_json_file("work_item_process_owner.json"))


def delete_assignment_rules():
	delete_assignment_rule(get_assignment_rule_json_file("work_item_developer.json"))
	delete_assignment_rule(get_assignment_rule_json_file("work_item_process_owner.json"))
