# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Row-level visibility for Social Post — layered under role-based DocPerms."""

import frappe
from es_social.social.utils import (
    are_connected,
    build_post_visibility_sql,
    get_group_ids,
)

PRIVILEGED = {"System Manager", "Social Moderator", "Social Admin", "Administrator"}


def get_permission_query_conditions(user=None):
    user = user or frappe.session.user
    if user == "Administrator" or PRIVILEGED & set(frappe.get_roles(user)):
        return ""
    if user == "Guest":
        # guests only ever see public, non-deleted posts
        return "(`tabSocial Post`.visibility = 'Public' and `tabSocial Post`.is_deleted = 0)"
    return build_post_visibility_sql(user)


def has_permission(doc, ptype="read", user=None):
    user = user or frappe.session.user
    if user == "Administrator" or PRIVILEGED & set(frappe.get_roles(user)):
        return True
    if doc.author == user:
        return True
    if ptype != "read":
        # write/delete restricted to owner (+ privileged handled above)
        return False
    if doc.get("is_deleted"):
        return False
    if doc.visibility == "Public":
        return True
    if doc.visibility == "Connections":
        return are_connected(user, doc.author)
    if doc.visibility == "Group" and doc.group:
        return doc.group in get_group_ids(user)
    return False
