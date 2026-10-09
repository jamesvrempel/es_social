# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""v0.7: seed the new guest-browsing settings on existing sites.

New fields on a Single doctype have no stored value after migrate, so set the
defaults explicitly (guest browsing on, Frappe's built-in sign-up page).
"""

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
    if _unset("allow_guest_browsing"):
        frappe.db.set_single_value("ES Social Settings", "allow_guest_browsing", 1)
    if _unset("signup_url"):
        frappe.db.set_single_value("ES Social Settings", "signup_url", "/login#signup")
    frappe.clear_document_cache("ES Social Settings", "ES Social Settings")
