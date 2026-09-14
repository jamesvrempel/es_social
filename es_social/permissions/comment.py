# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Comment visibility follows the visibility of its parent post."""

import frappe
from es_social.social.utils import build_post_visibility_sql

PRIVILEGED = {"System Manager", "Social Moderator", "Social Admin", "Administrator"}


def get_permission_query_conditions(user=None):
    user = user or frappe.session.user
    if user == "Administrator" or PRIVILEGED & set(frappe.get_roles(user)):
        return ""
    if user == "Guest":
        inner = "(p2.visibility = 'Public' and p2.is_deleted = 0)"
    else:
        inner = build_post_visibility_sql(user, alias="p2")
    return (
        "`tabSocial Comment`.reference_post in "
        f"(select p2.name from `tabSocial Post` p2 where {inner})"
    )
