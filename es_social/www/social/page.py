# Copyright (c) 2026, Enterprise Systems Australia and contributors
import frappe

from es_social.social.utils import apply_guest_context, guard_page


def get_context(context):
    guard_page("/social/pages")
    apply_guest_context(context)
    slug = frappe.form_dict.get("slug")
    if not context.es_flags.get("pages") or not frappe.db.exists("Social Page", {"slug": slug}):
        raise frappe.DoesNotExistError
    context.slug = slug
    context.no_cache = 1
    context.show_sidebar = False
    return context
