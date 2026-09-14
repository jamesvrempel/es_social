# Copyright (c) 2026, Enterprise Systems Australia and contributors
import frappe


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/social/groups"
        raise frappe.Redirect
    context.no_cache = 1
    context.show_sidebar = False
    return context
