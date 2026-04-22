
import frappe

def execute():
    """Update WI- series to 230 so next record is WI-231"""
    frappe.db.sql("""INSERT INTO `tabSeries` (name, current) VALUES ('WI-', 230) 
                     ON DUPLICATE KEY UPDATE current = 230""")
    frappe.db.commit()