# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""v0.8: seed social sign-in / customer provisioning settings on existing sites."""

import frappe

def _unset(field):
    """True when the Single has never stored this field (new after migrate).
    get_single_value() casts a missing Check to 0, so query tabSingles directly."""
    return not frappe.db.sql(
        "select 1 from `tabSingles` where doctype=%s and field=%s",
        ("ES Social Settings", field),
    )


def execute():
    frappe.reload_doc("es_social", "doctype", "es_social_settings")
    if _unset("enable_social_login"):
        frappe.db.set_single_value("ES Social Settings", "enable_social_login", 1)
    if _unset("signup_customer_scope"):
        frappe.db.set_single_value("ES Social Settings", "signup_customer_scope", "Social login sign-ups")
    frappe.clear_document_cache("ES Social Settings", "ES Social Settings")
