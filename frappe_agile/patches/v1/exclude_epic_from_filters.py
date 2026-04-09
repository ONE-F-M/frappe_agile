import frappe
from frappe_agile.setup.setup import create_list_filters, create_sprint_board_kanban


def execute():
	"""Exclude 'Epic' work item type from Backlog, Sprint Kanban List View, and Sprint Board filters.

	Updates saved List Filters and the Sprint Board Kanban Board base filter to add
	work_item_type != 'Epic' so only User Story, Bug, and Task items are visible
	in Backlog and Sprint Kanban views.
	"""
	create_list_filters()
	create_sprint_board_kanban()
