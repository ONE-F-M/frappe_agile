app_name = "frappe_agile"
app_title = "Frappe Agile"
app_publisher = "One FM"
app_description = "Agile project management for Frappe"
app_email = "s.shariff@one-fm.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "frappe_agile",
# 		"logo": "/assets/frappe_agile/logo.png",
# 		"title": "Frappe Agile",
# 		"route": "/frappe_agile",
# 		"has_permission": "frappe_agile.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/frappe_agile/css/frappe_agile.css"
# app_include_js = "/assets/frappe_agile/js/frappe_agile.js"

# include js, css files in header of web template
# web_include_css = "/assets/frappe_agile/css/frappe_agile.css"
# web_include_js = "/assets/frappe_agile/js/frappe_agile.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "frappe_agile/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
doctype_list_js = {"Work Item": "public/js/work_item_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "frappe_agile/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "frappe_agile.utils.jinja_methods",
# 	"filters": "frappe_agile.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "frappe_agile.install.before_install"
after_install = "frappe_agile.setup.setup.after_install"

# Uninstallation
# ------------

before_uninstall = "frappe_agile.setup.setup.before_uninstall"
# after_uninstall = "frappe_agile.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "frappe_agile.utils.before_app_install"
# after_app_install = "frappe_agile.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "frappe_agile.utils.before_app_uninstall"
# after_app_uninstall = "frappe_agile.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "frappe_agile.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Sprint": {
		"on_update": "frappe_agile.setup.setup.update_backlog_list_filter",
		"on_trash": "frappe_agile.setup.setup.update_backlog_list_filter",
	},
	"Work Item": {
		# Keep the status field in sync with the workflow_state (workflow is authoritative)
		"validate": [
			"frappe_agile.frappe_agile.doctype.work_item.work_item.sync_status_from_workflow",
			"frappe_agile.frappe_agile.doctype.sprint.sprint.validate_work_item_sprint",
		],
		# Recalculate Sprint.expected_velocity whenever a Work Item changes sprint or story_points
		"on_update": "frappe_agile.frappe_agile.doctype.sprint.sprint.update_sprint_velocity",
		"on_trash": "frappe_agile.frappe_agile.doctype.sprint.sprint.update_sprint_velocity",
	},
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"frappe_agile.tasks.all"
# 	],
# 	"daily": [
# 		"frappe_agile.tasks.daily"
# 	],
# 	"hourly": [
# 		"frappe_agile.tasks.hourly"
# 	],
# 	"weekly": [
# 		"frappe_agile.tasks.weekly"
# 	],
# 	"monthly": [
# 		"frappe_agile.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "frappe_agile.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "frappe_agile.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "frappe_agile.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["frappe_agile.utils.before_request"]
# after_request = ["frappe_agile.utils.after_request"]

# Job Events
# ----------
# before_job = ["frappe_agile.utils.before_job"]
# after_job = ["frappe_agile.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"frappe_agile.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

