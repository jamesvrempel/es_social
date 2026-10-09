# Copyright (c) 2026, Enterprise Systems Australia and contributors
import frappe

from es_social.social.utils import guard_page, apply_guest_context


def get_context(context):
    guard_page("/social/groups")
    apply_guest_context(context)
    context.no_cache = 1
    context.show_sidebar = False
    return context
