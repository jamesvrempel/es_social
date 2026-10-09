# Copyright (c) 2026, Enterprise Systems Australia and contributors
"""v0.9.4: default the new Branding option on existing sites."""

import frappe


def execute():
    frappe.reload_doc("es_social", "doctype", "es_social_settings")
    if not frappe.db.sql("select 1 from `tabSingles` where doctype='ES Social Settings' and field='brand_source'"):
        frappe.db.set_single_value("ES Social Settings", "brand_source", "Website name")
    frappe.clear_document_cache("ES Social Settings", "ES Social Settings")
