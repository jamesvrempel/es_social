# Copyright (c) 2026, Enterprise Systems Australia and contributors
import frappe


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/social"
        raise frappe.Redirect

    slug = frappe.form_dict.get("slug")
    context.slug = slug
    context.no_cache = 1
    context.show_sidebar = False
    return context
