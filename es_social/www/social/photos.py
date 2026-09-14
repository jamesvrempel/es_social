# Copyright (c) 2026, Enterprise Systems Australia and contributors
import frappe


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/social/photos"
        raise frappe.Redirect
    context.slug = frappe.form_dict.get("u")
    context.no_cache = 1
    context.show_sidebar = False
    return context
