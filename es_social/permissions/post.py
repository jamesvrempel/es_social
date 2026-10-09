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
        return ("(`tabSocial Post`.visibility = 'Public' and `tabSocial Post`.is_deleted = 0"
                " and coalesce(`tabSocial Post`.approval_status, 'Approved') = 'Approved')")
    return build_post_visibility_sql(user)


def has_permission(doc, ptype="read", user=None):
    user = user or frappe.session.user
    if user == "Guest":
        # anonymous visitors: read-only, public content only
        if ptype != "read" or doc.get("is_deleted") or not _approved(doc):
            return False
        if doc.visibility == "Public":
            return True
        return _in_public_group(doc)
    if user == "Administrator" or PRIVILEGED & set(frappe.get_roles(user)):
        return True
    if doc.author == user:
        return True
    if ptype != "read":
        # write/delete restricted to owner (+ privileged handled above)
        return False
    if doc.get("is_deleted"):
        return False
    from es_social.social.moderation import is_blocked, can_moderate_group
    if is_blocked(user, doc.author):
        return False
    if not _approved(doc):
        # pending posts: author (above) and that group's admins only
        return bool(doc.get("group")) and can_moderate_group(doc.group, user)
    if doc.visibility == "Public":
        return True
    if doc.visibility == "Connections":
        return are_connected(user, doc.author)
    if doc.visibility == "Group" and doc.group:
        return doc.group in get_group_ids(user) or _in_public_group(doc)
    return False


def _approved(doc):
    return (doc.get("approval_status") or "Approved") == "Approved"


def _in_public_group(doc):
    """Posts inside a Public group are readable by anyone (Closed/Secret groups
    still require membership)."""
    if doc.visibility != "Group" or not doc.group:
        return False
    return frappe.db.get_value("Social Group", doc.group, "privacy") == "Public"


def can_read_post(post, user=None):
    """Direct visibility check that works for Guest too.

    frappe.has_permission() first checks role DocPerms, which Guest doesn't
    have, so read endpoints call this instead of frappe.has_permission().
    """
    user = user or frappe.session.user
    if isinstance(post, str):
        if not frappe.db.exists("Social Post", post):
            return False
        post = frappe.get_doc("Social Post", post)
    return has_permission(post, "read", user)
