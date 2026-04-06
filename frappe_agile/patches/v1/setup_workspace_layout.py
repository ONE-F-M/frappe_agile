import frappe

def execute():
	# Seed Sprint Report if it doesn't exist
	if not frappe.db.exists("Report", "Sprint Report"):
		doc = frappe.get_doc({
			"doctype": "Report",
			"report_name": "Sprint Report",
			"ref_doctype": "Sprint",
			"report_type": "Script Report",
			"is_standard": "Yes",
			"module": "Frappe Agile",
			"roles": [{"role": "System Manager"}]
		})
		doc.insert(ignore_permissions=True)
	
	# Seed or update Frappe Agile Workspace
	w_name = "Frappe Agile"
	if frappe.db.exists("Workspace", w_name):
		doc = frappe.get_doc("Workspace", w_name)
	else:
		doc = frappe.get_doc({
			"doctype": "Workspace",
			"name": w_name,
			"title": "Frappe Agile",
			"label": "Frappe Agile",
			"module": "Frappe Agile",
			"is_standard": 1,
			"public": 1,
			"icon": "clipboard",
			"roles": [{"role": "System Manager"}]
		})

	# Adjust sequence so it's placed among other main modules
	doc.sequence_id = 4.0
	
	# Setting content for specific block rendering (header cards)
	doc.content = '[{"id":"agile_doctypes","type":"header","data":{"text":"<span class=\\"h4\\">Agile Planning</span>","col":12}},{"id":"sprint","type":"shortcut","data":{"shortcut_name":"Sprint","col":3}},{"id":"work_item","type":"shortcut","data":{"shortcut_name":"Work Item","col":3}},{"id":"reports_header","type":"header","data":{"text":"<span class=\\"h4\\">Reports</span>","col":12}},{"id":"sprint_report","type":"shortcut","data":{"shortcut_name":"Sprint Report","col":3}},{"id":"sprint_summary","type":"shortcut","data":{"shortcut_name":"Sprint Summary","col":3}}]'

	# Link layout for the Workspace page and Sidebar
	doc.links = []
	
	# --- Agile Planning ---
	doc.append("links", {
		"label": "Agile Planning",
		"type": "Card Break",
		"hidden": 0,
		"is_query_report": 0
	})
	doc.append("links", {
		"label": "Sprint",
		"link_to": "Sprint",
		"type": "Link",
		"link_type": "DocType",
		"hidden": 0,
		"is_query_report": 0
	})
	doc.append("links", {
		"label": "Work Item",
		"link_to": "Work Item",
		"type": "Link",
		"link_type": "DocType",
		"hidden": 0,
		"is_query_report": 0
	})
	# Notice: Work Item Template does not exist yet so we omit it from links to prevent validation error
	
	# --- Reports ---
	doc.append("links", {
		"label": "Reports",
		"type": "Card Break",
		"hidden": 0,
		"is_query_report": 0
	})
	doc.append("links", {
		"label": "Sprint Report",
		"link_to": "Sprint Report",
		"type": "Link",
		"link_type": "Report",
		"hidden": 0,
		"is_query_report": 1
	})
	doc.append("links", {
		"label": "Sprint Summary",
		"link_to": "Sprint Summary",
		"type": "Link",
		"link_type": "Report",
		"hidden": 0,
		"is_query_report": 1
	})

	# Shortcuts (These make the individual shortcuts functional)
	doc.shortcuts = []
	doc.append("shortcuts", {"label": "Sprint", "link_to": "Sprint", "type": "DocType"})
	doc.append("shortcuts", {"label": "Work Item", "link_to": "Work Item", "type": "DocType"})
	doc.append("shortcuts", {"label": "Sprint Report", "link_to": "Sprint Report", "type": "Report"})
	doc.append("shortcuts", {"label": "Sprint Summary", "link_to": "Sprint Summary", "type": "Report"})

	doc.save(ignore_permissions=True)
