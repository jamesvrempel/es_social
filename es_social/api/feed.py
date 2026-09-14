# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Feed assembly. All reads honour permission_query_conditions automatically."""

import frappe
from frappe.utils import cint

from es_social.social.utils import require_login, get_group_ids, get_member_role

POST_FIELDS = [
    "name", "author", "author_profile", "content", "post_type", "visibility",
    "group", "shared_post", "posted_on", "like_count", "comment_count",
    "share_count", "pinned", "link_url", "link_title", "link_image", "video_url",
]


def _author_map(user_ids):
    if not user_ids:
        return {}
    rows = frappe.get_all(
        "Social Profile",
        filters={"user": ("in", list(user_ids))},
        fields=["user", "display_name", "profile_image", "profile_slug"],
    )
    out = {r.user: r for r in rows}
    # fall back to User.full_name for anyone without a profile row
    missing = [u for u in user_ids if u not in out]
    if missing:
        for u in frappe.get_all("User", filters={"name": ("in", missing)},
                                fields=["name", "full_name", "user_image"]):
            out[u.name] = frappe._dict(
                user=u.name, display_name=u.full_name or u.name,
                profile_image=u.user_image, profile_slug=None)
    return out


def _media_map(post_names):
    if not post_names:
        return {}
    rows = frappe.get_all(
        "Social Post Media",
        filters={"parent": ("in", post_names), "parenttype": "Social Post"},
        fields=["parent", "image", "caption", "sort_order"],
        order_by="sort_order asc",
    )
    out = {}
    for r in rows:
        out.setdefault(r.parent, []).append({"image": r.image, "caption": r.caption})
    return out


def _my_reactions(post_names, viewer):
    if not post_names:
        return {}
    rows = frappe.get_all(
        "Social Reaction",
        filters={"reference_doctype": "Social Post",
                 "reference_name": ("in", post_names), "user": viewer},
        fields=["reference_name", "reaction_type"],
    )
    return {r.reference_name: r.reaction_type for r in rows}


def _top_comments(post_names, viewer, per_post=2):
    if not post_names:
        return {}
    rows = frappe.get_all(
        "Social Comment",
        filters={"reference_post": ("in", post_names), "is_deleted": 0},
        fields=["name", "reference_post", "author", "content", "posted_on", "like_count"],
        order_by="posted_on desc",
        limit_page_length=len(post_names) * per_post * 3 + 20,
    )
    authors = _author_map({r.author for r in rows})
    grouped = {}
    for r in rows:
        bucket = grouped.setdefault(r.reference_post, [])
        if len(bucket) >= per_post:
            continue
        a = authors.get(r.author)
        bucket.append({
            "name": r.name, "author": r.author,
            "author_name": a.display_name if a else r.author,
            "author_image": a.profile_image if a else None,
            "content": r.content, "posted_on": str(r.posted_on),
            "like_count": r.like_count,
        })
    # display oldest-first within the shown pair
    for k in grouped:
        grouped[k] = list(reversed(grouped[k]))
    return grouped


def enrich_posts(posts, viewer, depth=1):
    """Attach author, media, viewer reaction, top comments and shared-post preview."""
    if not posts:
        return []
    names = [p["name"] for p in posts]
    author_ids = {p["author"] for p in posts}
    shared_ids = [p["shared_post"] for p in posts if p.get("shared_post")]

    authors = _author_map(author_ids)
    media = _media_map(names)
    my_reactions = _my_reactions(names, viewer)
    comments = _top_comments(names, viewer)

    shared_map = {}
    if shared_ids and depth > 0:
        shared_rows = frappe.get_all(
            "Social Post", filters={"name": ("in", shared_ids)}, fields=POST_FIELDS)
        shared_map = {p["name"]: p for p in enrich_posts(
            [dict(p) for p in shared_rows], viewer, depth=0)}

    out = []
    for p in posts:
        a = authors.get(p["author"])
        p = dict(p)
        p["posted_on"] = str(p.get("posted_on"))
        p["author_name"] = a.display_name if a else p["author"]
        p["author_image"] = a.profile_image if a else None
        p["author_slug"] = a.profile_slug if a else None
        p["media"] = media.get(p["name"], [])
        p["my_reaction"] = my_reactions.get(p["name"])
        p["top_comments"] = comments.get(p["name"], [])
        p["can_edit"] = (p["author"] == viewer)
        if p.get("video_url"):
            from es_social.social.video import embed_for
            p["video_embed"] = embed_for(p["video_url"])
        if p.get("shared_post"):
            p["shared"] = shared_map.get(p["shared_post"])
        out.append(p)
    return out


@frappe.whitelist()
def get_feed(start=0, page_length=20):
    """Home feed: everything the viewer is permitted to see, newest first."""
    viewer = require_login()
    posts = frappe.get_list(
        "Social Post",
        filters={"is_deleted": 0},
        fields=POST_FIELDS,
        order_by="pinned desc, posted_on desc",
        start=cint(start),
        page_length=cint(page_length) or 20,
    )
    return enrich_posts(posts, viewer)


@frappe.whitelist()
def get_profile_feed(user, start=0, page_length=20):
    """Posts by a specific user that the viewer may see."""
    viewer = require_login()
    posts = frappe.get_list(
        "Social Post",
        filters={"is_deleted": 0, "author": user, "visibility": ("!=", "Group")},
        fields=POST_FIELDS,
        order_by="pinned desc, posted_on desc",
        start=cint(start),
        page_length=cint(page_length) or 20,
    )
    return enrich_posts(posts, viewer)


@frappe.whitelist()
def get_group_feed(group, start=0, page_length=20):
    """Posts within a group. Secret/Closed groups require membership."""
    viewer = require_login()
    privacy = frappe.db.get_value("Social Group", group, "privacy")
    if privacy in ("Closed", "Secret") and group not in get_group_ids(viewer):
        frappe.throw(frappe._("You must be a member to view this group."), frappe.PermissionError)
    posts = frappe.get_list(
        "Social Post",
        filters={"is_deleted": 0, "group": group},
        fields=POST_FIELDS,
        order_by="pinned desc, posted_on desc",
        start=cint(start),
        page_length=cint(page_length) or 20,
    )
    return enrich_posts(posts, viewer)
