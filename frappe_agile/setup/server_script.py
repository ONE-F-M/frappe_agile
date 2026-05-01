# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt
"""
Setup functions for Server Scripts — called from after_install, before_uninstall,
and the create_server_scripts patch.
"""

from frappe_agile.frappe_agile.custom.server_script.server_script import (
	get_server_script_json_file,
	create_server_script,
	delete_server_script,
)

# All bundled server script JSON filenames
SERVER_SCRIPT_FILES = [
	"validate_ai_tools_feedback.json",
	"validate_assignee_user.json",
	"validate_pr_link.json",
	"validate_pr_reviewer.json",
	"validate_prompt_count.json",
]


def create_server_scripts():
	"""Create or update all bundled Server Scripts."""
	for file_name in SERVER_SCRIPT_FILES:
		create_server_script(get_server_script_json_file(file_name))


def delete_server_scripts():
	"""Delete all bundled Server Scripts (used on uninstall)."""
	for file_name in SERVER_SCRIPT_FILES:
		delete_server_script(get_server_script_json_file(file_name))
