# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Member safety: blocking and reporting members."""

import frappe
from frappe.utils import now_datetime

from es_social.social.moderation import clear_block_cache
from es_social.social.utils import (
    clear_connection_cache, get_viewer, pair_key, require_login,
)


def _resolve_user(user=None, slug=None):
    if slug:
        user = frappe.db.get_value("Social Profile", {"profile_slug": slug}, "user")
    if not user or not frappe.db.exists("User", user):
        frappe.throw(frappe._("Member not found."))
    return user


@frappe.whitelist()
def block_user(user=None, slug=None):
    """Block a member: hides each other's posts and comments, ends any
    friendship and prevents friend requests, comments, reactions and messages."""
    viewer = require_login()
    other = _resolve_user(user, slug)
    if other == viewer:
        frappe.throw(frappe._("You can't block yourself."))
    if other in ("Administrator",):
        frappe.throw(frappe._("This account can't be blocked."))
    if not frappe.db.exists("Social Block", {"blocker": viewer, "blocked": other}):
        frappe.get_doc({"doctype": "Social Block", "blocker": viewer, "blocked": other,
                        "blocked_on": now_datetime()}).insert(ignore_permissions=True)
    # end any friendship / pending request
    conn = frappe.db.get_value("Social Connection", {"pair_key": pair_key(viewer, other)}, "name")
    if conn:
        frappe.delete_doc("Social Connection", conn, ignore_permissions=True, force=True)
    clear_block_cache(viewer, other)
    clear_connection_cache(viewer, other)
    frappe.db.commit()
    return {"ok": True, "blocked": True}


@frappe.whitelist()
def unblock_user(user=None, slug=None):
    viewer = require_login()
    other = _resolve_user(user, slug)
    for name in frappe.get_all("Social Block", filters={"blocker": viewer, "blocked": other}, pluck="name"):
        frappe.delete_doc("Social Block", name, ignore_permissions=True, force=True)
    clear_block_cache(viewer, other)
    frappe.db.commit()
    return {"ok": True, "blocked": False}


@frappe.whitelist(allow_guest=True)
def list_blocked():
    viewer = get_viewer()
    if viewer == "Guest":
        return []
    users = frappe.get_all("Social Block", filters={"blocker": viewer}, pluck="blocked")
    if not users:
        return []
    rows = frappe.get_all("Social Profile", filters={"user": ("in", users)},
                          fields=["display_name", "profile_slug", "profile_image"])
    return rows


@frappe.whitelist()
def report_user(slug, reason, details=None):
    from es_social.api.posts import report_content
    return report_content(slug, reason, reference_doctype="User", details=details)
