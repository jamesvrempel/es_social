# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Album privacy + photo visibility (photos inherit their album's privacy)."""

import frappe
from es_social.social.utils import get_connection_ids, are_connected

PRIVILEGED = {"System Manager", "Social Moderator", "Social Admin", "Administrator"}


def _album_visibility_sql(user, alias="`tabSocial Album`"):
    esc = frappe.db.escape
    clauses = [
        f"{alias}.owner_user = {esc(user)}",
        f"{alias}.privacy = 'Public'",
    ]
    conns = get_connection_ids(user)
    if conns:
        in_list = ", ".join(esc(c) for c in conns)
        clauses.append(f"({alias}.privacy = 'Connections' and {alias}.owner_user in ({in_list}))")
    return "(" + " or ".join(clauses) + ")"


def get_permission_query_conditions(user=None):
    user = user or frappe.session.user
    if user == "Administrator" or PRIVILEGED & set(frappe.get_roles(user)):
        return ""
    if user == "Guest":
        return "(`tabSocial Album`.privacy = 'Public')"
    return _album_visibility_sql(user)


def has_permission(doc, ptype="read", user=None):
    user = user or frappe.session.user
    if user == "Administrator" or PRIVILEGED & set(frappe.get_roles(user)):
        return True
    if doc.owner_user == user:
        return True
    if ptype != "read":
        return False
    if doc.privacy == "Public":
        return True
    if doc.privacy == "Connections":
        return are_connected(user, doc.owner_user)
    return False


def get_photo_permission_query_conditions(user=None):
    user = user or frappe.session.user
    if user == "Administrator" or PRIVILEGED & set(frappe.get_roles(user)):
        return ""
    if user == "Guest":
        inner = "(a2.privacy = 'Public')"
    else:
        inner = _album_visibility_sql(user, alias="a2")
    return (
        "`tabSocial Photo`.album in "
        f"(select a2.name from `tabSocial Album` a2 where {inner})"
    )
