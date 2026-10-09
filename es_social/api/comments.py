# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Comment lifecycle."""

import frappe

from es_social.social.utils import (
    require_login, get_viewer, enforce_rate_limit, check_content, get_settings,
    get_group_ids, scrub_for_guest,
)
from es_social.api.feed import _author_map, _fallback_name
from es_social.permissions.post import can_read_post


@frappe.whitelist()
def add_comment(reference_post, content, parent_comment=None):
    viewer = require_login()
    settings = get_settings()
    enforce_rate_limit("comment", settings.comments_per_minute)
    held = check_content(content, allow_hold=True)

    from es_social.social.moderation import assert_not_blocked, set_content_hidden, queue_for_review
    post_author = frappe.db.get_value("Social Post", reference_post, "author")
    assert_not_blocked(viewer, post_author, frappe._("You can't comment on this post."))
    if not can_read_post(reference_post, viewer):
        frappe.throw(frappe._("You can't comment on this post."), frappe.PermissionError)
    vis, group = frappe.db.get_value("Social Post", reference_post, ["visibility", "group"])
    if vis == "Group" and group and group not in get_group_ids(viewer):
        privileged = {"System Manager", "Social Moderator", "Social Admin"} & set(frappe.get_roles(viewer))
        if not privileged:
            frappe.throw(frappe._("Join the group to comment."), frappe.PermissionError)

    doc = frappe.new_doc("Social Comment")
    doc.reference_post = reference_post
    doc.parent_comment = parent_comment
    doc.author = viewer
    doc.content = content
    doc.insert()
    if held:
        set_content_hidden("Social Comment", doc.name, True)
        queue_for_review("Social Comment", doc.name, details="Held automatically: blocked keyword")
        frappe.db.commit()
        return {"held": True, "message": frappe._("Your comment is awaiting review.")}
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


@frappe.whitelist(allow_guest=True)
def list_comments(reference_post, start=0, page_length=50):
    viewer = get_viewer()
    if not can_read_post(reference_post, viewer):
        frappe.throw(frappe._("You can't view this post."), frappe.PermissionError)
    rows = frappe.get_all(
        "Social Comment",
        filters={"reference_post": reference_post, "is_deleted": 0},
        fields=["name", "author", "content", "posted_on", "like_count", "parent_comment"],
        order_by="posted_on asc",
        start=int(start), page_length=min(int(page_length), 200),
    )
    from es_social.social.moderation import get_block_ids
    blocked = get_block_ids(viewer)
    rows = [r for r in rows if r.author not in blocked]
    authors = _author_map({r.author for r in rows})
    for r in rows:
        a = authors.get(r.author)
        r["author_name"] = a.display_name if a else _fallback_name(r.author, viewer)
        r["author_image"] = a.profile_image if a else None
        r["posted_on"] = str(r.posted_on)
        scrub_for_guest(r, viewer)
    return rows
