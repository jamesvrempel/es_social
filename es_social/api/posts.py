# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Post lifecycle + reactions."""

import json

import frappe

from es_social.social.utils import (
    require_login,
    enforce_rate_limit,
    check_content,
    get_settings,
    get_group_ids,
    REACTION_TYPES,
)
from es_social.api.feed import enrich_posts, POST_FIELDS


def _load(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


@frappe.whitelist()
def create_post(content=None, post_type="Status", visibility=None, group=None,
                media=None, shared_post=None, link_url=None, link_title=None,
                link_image=None, video_url=None):
    viewer = require_login()
    settings = get_settings()
    enforce_rate_limit("post", settings.posts_per_minute)
    check_content(content)

    media = _load(media) or []

    # Validate video link (allowlist) up-front; a video post ignores photo media.
    if video_url:
        from es_social.social.video import parse_video_url
        if not parse_video_url(video_url):
            frappe.throw(frappe._("That video link isn't supported. Use a YouTube or Vimeo URL."))
        media = []

    if not content and not media and not shared_post and not link_url and not video_url:
        frappe.throw(frappe._("Your post is empty."))

    if visibility == "Group" or group:
        visibility = "Group"
        if not group or group not in get_group_ids(viewer):
            frappe.throw(frappe._("You can only post to groups you belong to."),
                         frappe.PermissionError)

    doc = frappe.new_doc("Social Post")
    doc.author = viewer
    doc.content = content
    doc.visibility = visibility or settings.default_visibility or "Public"
    doc.group = group
    doc.shared_post = shared_post
    doc.link_url = link_url
    doc.link_title = link_title
    doc.link_image = link_image
    doc.video_url = video_url
    if video_url:
        doc.post_type = "Video"
    elif shared_post:
        doc.post_type = "Shared"
    else:
        doc.post_type = post_type or "Status"
    for i, m in enumerate(media):
        img = m.get("image") if isinstance(m, dict) else m
        cap = m.get("caption") if isinstance(m, dict) else None
        if img:
            doc.append("media", {"image": img, "caption": cap, "sort_order": i})
    if media and doc.post_type == "Status":
        doc.post_type = "Photo"
    doc.insert()
    _attach_media_files(doc)
    frappe.db.commit()

    fresh = frappe.db.get_value("Social Post", doc.name, POST_FIELDS, as_dict=True)
    return enrich_posts([dict(fresh)], viewer)[0]


def _attach_media_files(doc):
    """Link uploaded File records to the post so they are tracked and are
    removed with it. Best-effort — never blocks posting."""
    for row in doc.get("media") or []:
        if not row.image:
            continue
        try:
            fname = frappe.db.get_value(
                "File", {"file_url": row.image, "attached_to_name": ["in", ["", None]]}, "name"
            )
            if fname:
                frappe.db.set_value("File", fname, {
                    "attached_to_doctype": "Social Post",
                    "attached_to_name": doc.name,
                    "attached_to_field": "media",
                }, update_modified=False)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "es_social: media attach failed")


@frappe.whitelist()
def edit_post(name, content):
    viewer = require_login()
    doc = frappe.get_doc("Social Post", name)
    if doc.author != viewer and not _is_privileged(viewer):
        frappe.throw(frappe._("You can only edit your own posts."), frappe.PermissionError)
    check_content(content)
    doc.content = content
    doc.save()
    return {"ok": True}


@frappe.whitelist()
def delete_post(name):
    viewer = require_login()
    doc = frappe.get_doc("Social Post", name)
    if doc.author != viewer and not _is_privileged(viewer):
        frappe.throw(frappe._("You can only delete your own posts."), frappe.PermissionError)
    doc.db_set("is_deleted", 1)
    return {"ok": True}


@frappe.whitelist()
def share_post(shared_post, content=None, visibility=None):
    return create_post(content=content, shared_post=shared_post, visibility=visibility)


@frappe.whitelist()
def react(reference_name, reaction_type="Like", reference_doctype="Social Post"):
    """Upsert a reaction. Returns the new count and the viewer's reaction."""
    viewer = require_login()
    if reaction_type not in REACTION_TYPES:
        frappe.throw(frappe._("Unknown reaction."))
    if reference_doctype not in ("Social Post", "Social Comment"):
        frappe.throw(frappe._("Unsupported target."))

    existing = frappe.db.get_value(
        "Social Reaction",
        {"reference_doctype": reference_doctype, "reference_name": reference_name,
         "user": viewer},
        "name",
    )
    if existing:
        frappe.db.set_value("Social Reaction", existing, "reaction_type", reaction_type)
        my = reaction_type
    else:
        doc = frappe.new_doc("Social Reaction")
        doc.reference_doctype = reference_doctype
        doc.reference_name = reference_name
        doc.user = viewer
        doc.reaction_type = reaction_type
        doc.insert(ignore_permissions=True)
        my = reaction_type
    frappe.db.commit()
    count = frappe.db.get_value(reference_doctype, reference_name, "like_count")
    return {"like_count": count, "my_reaction": my}


@frappe.whitelist()
def unreact(reference_name, reference_doctype="Social Post"):
    viewer = require_login()
    existing = frappe.db.get_value(
        "Social Reaction",
        {"reference_doctype": reference_doctype, "reference_name": reference_name,
         "user": viewer},
        "name",
    )
    if existing:
        frappe.delete_doc("Social Reaction", existing, ignore_permissions=True)
        frappe.db.commit()
    count = frappe.db.get_value(reference_doctype, reference_name, "like_count")
    return {"like_count": count, "my_reaction": None}


@frappe.whitelist()
def get_reactions(reference_name, reference_doctype="Social Post"):
    """Reaction breakdown for a target."""
    rows = frappe.db.sql(
        """select reaction_type, count(*) as c from `tabSocial Reaction`
           where reference_doctype=%s and reference_name=%s group by reaction_type""",
        (reference_doctype, reference_name), as_dict=True,
    )
    return {r.reaction_type: r.c for r in rows}


@frappe.whitelist()
def report_content(reference_name, reason, reference_doctype="Social Post", details=None):
    viewer = require_login()
    doc = frappe.get_doc({
        "doctype": "Social Report",
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "reported_by": viewer,
        "reason": reason,
        "details": details,
        "status": "Open",
    })
    doc.insert(ignore_permissions=True)
    return {"ok": True}


def _is_privileged(user):
    return bool({"System Manager", "Social Moderator", "Social Admin"} & set(frappe.get_roles(user)))
