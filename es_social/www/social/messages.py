# Copyright (c) 2026, Enterprise Systems Australia and contributors
import frappe

from es_social.social.utils import apply_guest_context, guard_page


def get_context(context):
    guard_page("/social/messages", guest_ok=False)
    apply_guest_context(context)
    if not context.es_flags.get("messaging"):
        raise frappe.PageDoesNotExistError
    context.open_with = frappe.form_dict.get("u") or ""
    context.no_cache = 1
    context.show_sidebar = False
    return context
