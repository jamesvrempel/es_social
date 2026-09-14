# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Comment lifecycle."""

import frappe

from es_social.social.utils import require_login, enforce_rate_limit, check_content, get_settings
from es_social.api.feed import _author_map


@frappe.whitelist()
def add_comment(reference_post, content, parent_comment=None):
    viewer = require_login()
    settings = get_settings()
    enforce_rate_limit("comment", settings.comments_per_minute)
    check_content(content)

    if not frappe.has_permission("Social Post", "read", doc=reference_post, user=viewer):
        frappe.throw(frappe._("You can't comment on this post."), frappe.PermissionError)

    doc = frappe.new_doc("Social Comment")
    doc.reference_post = reference_post
    doc.parent_comment = parent_comment
    doc.author = viewer
    doc.content = content
    doc.insert()
    frappe.db.commit()

    a = _author_map({viewer}).get(viewer)
    return {
        "name": doc.name,
        "author": viewer,
        "author_name": a.display_name if a else viewer,
        "author_image": a.profile_image if a else None,
        "content": doc.content,
        "posted_on": str(doc.posted_on),
        "like_count": 0,
        "parent_comment": parent_comment,
    }


@frappe.whitelist()
def delete_comment(name):
    viewer = require_login()
    doc = frappe.get_doc("Social Comment", name)
    privileged = {"System Manager", "Social Moderator", "Social Admin"} & set(frappe.get_roles(viewer))
    if doc.author != viewer and not privileged:
        frappe.throw(frappe._("You can only delete your own comments."), frappe.PermissionError)
    doc.db_set("is_deleted", 1)
    return {"ok": True}


@frappe.whitelist()
def list_comments(reference_post, start=0, page_length=50):
    viewer = require_login()
    if not frappe.has_permission("Social Post", "read", doc=reference_post, user=viewer):
        frappe.throw(frappe._("You can't view this post."), frappe.PermissionError)
    rows = frappe.get_all(
        "Social Comment",
        filters={"reference_post": reference_post, "is_deleted": 0},
        fields=["name", "author", "content", "posted_on", "like_count", "parent_comment"],
        order_by="posted_on asc",
        start=int(start), page_length=int(page_length),
    )
    authors = _author_map({r.author for r in rows})
    for r in rows:
        a = authors.get(r.author)
        r["author_name"] = a.display_name if a else r.author
        r["author_image"] = a.profile_image if a else None
        r["posted_on"] = str(r.posted_on)
    return rows
