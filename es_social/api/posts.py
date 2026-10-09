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
from es_social.social.moderation import (
    assert_not_blocked, can_moderate_group, content_group, content_owner,
    maybe_auto_hide, queue_for_review,
)


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
                link_image=None, video_url=None, page=None):
    """Public endpoint. Event posts are created only via events.create_event."""
    if post_type == "Event":
        post_type = "Status"
    return _create_post(content=content, post_type=post_type, visibility=visibility, group=group,
                        media=media, shared_post=shared_post, link_url=link_url, link_title=link_title,
                        link_image=link_image, video_url=video_url, page=page)


def _create_post(content=None, post_type="Status", visibility=None, group=None,
                 media=None, shared_post=None, link_url=None, link_title=None,
                 link_image=None, video_url=None, page=None, event=None):
    viewer = require_login()
    settings = get_settings()
    enforce_rate_limit("post", settings.posts_per_minute)
    held = check_content(content, allow_hold=True)

    media = _load(media) or []

    # Validate video link (allowlist) up-front; a video post ignores photo media.
    if video_url:
        from es_social.social.video import parse_video_url
        if not parse_video_url(video_url):
            frappe.throw(frappe._("That video link isn't supported. Use a YouTube or Vimeo URL."))
        media = []

    if not content and not media and not shared_post and not link_url and not video_url:
        frappe.throw(frappe._("Your post is empty."))

    if page:
        from es_social.api.pages import is_page_admin
        if not is_page_admin(page, viewer):
            frappe.throw(frappe._("Only page admins can post as this page."), frappe.PermissionError)
        visibility, group = "Public", None   # page posts are public
    elif visibility == "Group" or group:
        visibility = "Group"
        if not group or group not in get_group_ids(viewer):
            frappe.throw(frappe._("You can only post to groups you belong to."),
                         frappe.PermissionError)

    if shared_post:
        original_author = frappe.db.get_value("Social Post", shared_post, "author")
        assert_not_blocked(viewer, original_author)

    approval = "Approved"
    if held:
        approval = "Pending"
    elif group and frappe.db.get_value("Social Group", group, "post_approval") \
            and not can_moderate_group(group, viewer):
        approval = "Pending"

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
    doc.page = page
    doc.event = event
    doc.approval_status = approval
    if event:
        doc.post_type = "Event"
    elif video_url:
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
    if held:
        queue_for_review("Social Post", doc.name, reason="Other",
                         details="Held automatically: blocked keyword")
    elif approval == "Pending":
        _notify_group_moderators(group, doc.name, viewer)
    else:
        from es_social.social.fanout import on_post_published
        on_post_published(doc.name)
    frappe.db.commit()

    fresh = frappe.db.get_value("Social Post", doc.name, POST_FIELDS, as_dict=True)
    return enrich_posts([dict(fresh)], viewer)[0]


def _notify_group_moderators(group, post, author):
    from es_social.social.utils import notify
    gname = frappe.db.get_value("Social Group", group, "group_name") or group
    actor = frappe.db.get_value("User", author, "full_name") or "A member"
    for u in frappe.get_all("Social Group Member",
                            filters={"group": group, "status": "Active",
                                     "role": ("in", ["Admin", "Moderator"])}, pluck="user"):
        notify(u, frappe._("{0} posted in {1} — awaiting approval").format(actor, gname),
               reference_doctype="Social Post", reference_name=post,
               link=f"/social/group/{group}")


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
    held = check_content(content, allow_hold=True)
    doc.content = content
    if held and doc.approval_status == "Approved":
        doc.approval_status = "Pending"
    doc.save()
    if held:
        queue_for_review("Social Post", doc.name, details="Held automatically after edit: blocked keyword")
    return {"ok": True, "pending": bool(held)}


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
    owner = content_owner(reference_doctype, reference_name)
    assert_not_blocked(viewer, owner)
    if reference_doctype == "Social Post":
        from es_social.permissions.post import can_read_post
        if not can_read_post(reference_name, viewer):
            frappe.throw(frappe._("You can't react to this post."), frappe.PermissionError)

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


@frappe.whitelist(allow_guest=True)
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
    """Report a post, comment, message, page or member. One open report per
    reporter per item; N distinct reporters auto-hide content pending review."""
    viewer = require_login()
    if reference_doctype not in ("Social Post", "Social Comment", "User", "Social Message", "Social Page"):
        frappe.throw(frappe._("Unsupported target."))
    if reference_doctype == "User":
        # members are reported by profile slug from the UI; accept either
        reference_name = frappe.db.get_value("Social Profile", {"profile_slug": reference_name}, "user") \
            or reference_name
        if not frappe.db.exists("User", reference_name):
            frappe.throw(frappe._("Member not found."))
    elif not frappe.db.exists(reference_doctype, reference_name):
        frappe.throw(frappe._("Not found."))
    if reference_doctype == "Social Message":
        from es_social.api.messages import message_participant
        if not message_participant(reference_name, viewer):
            frappe.throw(frappe._("Not found."), frappe.PermissionError)

    enforce_rate_limit("report", 10)
    dup = frappe.db.exists("Social Report", {"reference_doctype": reference_doctype,
                                             "reference_name": reference_name,
                                             "reported_by": viewer, "status": "Open"})
    if not dup:
        frappe.get_doc({
            "doctype": "Social Report",
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "reported_by": viewer,
            "reported_user": content_owner(reference_doctype, reference_name),
            "group": content_group(reference_doctype, reference_name),
            "reason": reason if reason in REPORT_REASONS else "Other",
            "details": details,
            "status": "Open",
        }).insert(ignore_permissions=True)
        maybe_auto_hide(reference_doctype, reference_name)
        frappe.db.commit()
    return {"ok": True}


REPORT_REASONS = ["Spam", "Harassment", "Hate Speech", "Nudity", "Violence", "Misinformation", "Other"]


def _is_privileged(user):
    return bool({"System Manager", "Social Moderator", "Social Admin"} & set(frappe.get_roles(user)))
