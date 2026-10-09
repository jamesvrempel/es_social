# Copyright (c) 2026, Enterprise Systems Australia and contributors
import frappe

from es_social.social.utils import guard_page, apply_guest_context


def get_context(context):
    # Friends list & requests are personal — members only.
    guard_page("/social/connections", guest_ok=False)
    apply_guest_context(context)
    context.no_cache = 1
    context.show_sidebar = False
    return context
