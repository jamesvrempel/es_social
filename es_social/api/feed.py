# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Feed assembly. All reads honour permission_query_conditions automatically."""

import frappe
from frappe.utils import cint

from es_social.social.utils import (
    GUEST, get_viewer, get_group_ids, get_member_role, scrub_for_guest,
)
from es_social.social.moderation import get_block_ids
from es_social.social.cache import guest_cached, FeedTimer

POST_FIELDS = [
    "name", "author", "author_profile", "content", "post_type", "visibility",
    "group", "shared_post", "posted_on", "like_count", "comment_count",
    "share_count", "pinned", "link_url", "link_title", "link_image", "video_url",
    "page", "event", "approval_status",
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
    if not post_names or viewer == GUEST:
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
    blocked = get_block_ids(viewer)
    rows = [r for r in rows if r.author not in blocked]
    authors = _author_map({r.author for r in rows})
    grouped = {}
    for r in rows:
        bucket = grouped.setdefault(r.reference_post, [])
        if len(bucket) >= per_post:
            continue
        a = authors.get(r.author)
        bucket.append(scrub_for_guest({
            "name": r.name, "author": r.author,
            "author_name": a.display_name if a else _fallback_name(r.author, viewer),
            "author_image": a.profile_image if a else None,
            "content": r.content, "posted_on": str(r.posted_on),
            "like_count": r.like_count,
        }, viewer))
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

    pages = _page_map({p.get("page") for p in posts if p.get("page")})
    events = _event_map([p["event"] for p in posts if p.get("event")], viewer)

    shared_map = {}
    if shared_ids and depth > 0:
        from es_social.permissions.post import has_permission as _can_read
        shared_rows = frappe.get_all(
            "Social Post", filters={"name": ("in", shared_ids)},
            fields=POST_FIELDS + ["is_deleted"])
        # only embed a shared original the viewer may actually see
        shared_rows = [r for r in shared_rows if _can_read(r, "read", viewer)]
        for r in shared_rows:
            r.pop("is_deleted", None)
        shared_map = {p["name"]: p for p in enrich_posts(
            [dict(p) for p in shared_rows], viewer, depth=0)}

    out = []
    for p in posts:
        a = authors.get(p["author"])
        p = dict(p)
        p["posted_on"] = str(p.get("posted_on"))
        p["author_name"] = a.display_name if a else _fallback_name(p["author"], viewer)
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
        pg = pages.get(p.get("page"))
        if pg:
            # posted as a Page: the page is the visible author
            p["page_name"], p["page_slug"] = pg.page_name, pg.slug
            p["page_avatar"], p["page_verified"] = pg.avatar, pg.verified
        if p.get("event"):
            p["event_info"] = events.get(p["event"])
        p["pending"] = (p.get("approval_status") or "Approved") != "Approved"
        out.append(scrub_for_guest(p, viewer))
    return out


def _page_map(names):
    names = [n for n in names if n]
    if not names:
        return {}
    rows = frappe.get_all("Social Page", filters={"name": ("in", names)},
                          fields=["name", "page_name", "slug", "avatar", "verified"])
    return {r.name: r for r in rows}


def _event_map(names, viewer):
    if not names:
        return {}
    rows = frappe.get_all("Social Event", filters={"name": ("in", names)},
                          fields=["name", "title", "starts_on", "ends_on", "timezone", "venue",
                                  "online_url", "capacity", "going_count", "interested_count",
                                  "status", "item"])
    mine = {}
    if viewer != GUEST:
        mine = {r.event: r.status for r in frappe.get_all(
            "Social Event RSVP", filters={"event": ("in", names), "user": viewer},
            fields=["event", "status"])}
    out = {}
    for r in rows:
        d = dict(r)
        d["starts_on"] = str(r.starts_on) if r.starts_on else None
        d["ends_on"] = str(r.ends_on) if r.ends_on else None
        d["paid"] = bool(r.item)
        d.pop("item", None)
        d["my_rsvp"] = mine.get(r.name)
        d["full"] = bool(r.capacity) and (r.going_count or 0) >= r.capacity
        out[r.name] = d
    return out


def _fallback_name(user, viewer):
    """Display name when a user has no profile — never leak an email to guests."""
    if viewer == GUEST:
        return "Member"
    return user


def _list_posts(viewer, filters, **kwargs):
    """frappe.get_list for members (row-level permissions apply); explicit
    public-only filters via get_all for guests, who hold no DocPerms."""
    if viewer == GUEST:
        f = dict(filters)
        f["is_deleted"] = 0
        f["visibility"] = "Public"
        f["approval_status"] = "Approved"
        return frappe.get_all("Social Post", filters=f, **kwargs)
    # members: row-level conditions also apply approval + blocking rules
    return frappe.get_list("Social Post", filters=filters, **kwargs)


TOP_CANDIDATES = 200


@frappe.whitelist(allow_guest=True)
def get_feed(start=0, page_length=20, sort="latest"):
    """Home feed. sort="latest" (default, chronological) or "top" (ranked by
    engagement x your affinity with the author). Guests get the public
    timeline (cached briefly). With fan-out enabled, members read their inbox."""
    viewer = get_viewer()
    start, page_length = cint(start), cint(page_length) or 20
    sort = "top" if sort == "top" else "latest"

    def produce():
        with FeedTimer(f"home:{sort}", viewer):
            return _home_feed(viewer, start, page_length, sort)

    return guest_cached(viewer, "home", produce, start=start, n=page_length, sort=sort)


def _home_feed(viewer, start, page_length, sort):
    from es_social.social import fanout, ranking

    if sort == "top":
        since = frappe.utils.add_days(frappe.utils.now_datetime(), -7)
        candidates = _list_posts(viewer, {"is_deleted": 0, "posted_on": (">=", since)},
                                 fields=POST_FIELDS, order_by="posted_on desc",
                                 page_length=TOP_CANDIDATES)
        if len(candidates) < page_length:
            # quiet week: rank the most recent posts regardless of age
            candidates = _list_posts(viewer, {"is_deleted": 0}, fields=POST_FIELDS,
                                     order_by="posted_on desc", page_length=TOP_CANDIDATES)
        ranked = ranking.rank_personal([dict(p) for p in candidates], viewer)
        return enrich_posts(ranked[start:start + page_length], viewer)

    # Fan-out inbox (only once built for this member — see fanout.read_enabled).
    # An empty FIRST page falls through to the normal feed; an empty later page
    # simply means the end of the inbox.
    names = fanout.read_inbox(viewer, start, page_length) \
        if viewer != GUEST and fanout.read_enabled(viewer) else None
    if names == [] and start:
        return []
    if names:
        rows = frappe.get_list("Social Post", filters={"name": ("in", names), "is_deleted": 0},
                               fields=POST_FIELDS, page_length=len(names))
        order = {n: i for i, n in enumerate(names)}
        rows = sorted(rows, key=lambda r: order.get(r.name, 0))
        return enrich_posts(rows, viewer)

    # NB: no "pinned desc" here — pins are scoped to a group's own feed
    posts = _list_posts(viewer, {"is_deleted": 0}, fields=POST_FIELDS,
                        order_by="posted_on desc", start=start, page_length=page_length)
    return enrich_posts(posts, viewer)


@frappe.whitelist(allow_guest=True)
def get_trending(limit=5):
    """Public posts ranked by the hourly trending score (visible to guests)."""
    viewer = get_viewer()
    limit = min(cint(limit) or 5, 20)

    def produce():
        blocked = get_block_ids(viewer)
        filters = {"is_deleted": 0, "visibility": "Public", "approval_status": "Approved",
                   "score": (">", 0)}
        if blocked:
            filters["author"] = ("not in", list(blocked))
        rows = frappe.get_all("Social Post", filters=filters,
                              fields=["name", "author", "content", "like_count", "comment_count",
                                      "posted_on", "page"],
                              order_by="score desc", page_length=limit)
        authors = _author_map({r.author for r in rows})
        pages = _page_map({r.page for r in rows if r.page})
        out = []
        for r in rows:
            a, pg = authors.get(r.author), pages.get(r.page)
            out.append({
                "name": r.name,
                "snippet": frappe.utils.strip_html(r.content or "")[:140],
                "author_name": pg.page_name if pg else (a.display_name if a else _fallback_name(r.author, viewer)),
                "author_slug": None if pg else (a.profile_slug if a else None),
                "page_slug": pg.slug if pg else None,
                "like_count": r.like_count, "comment_count": r.comment_count,
                "posted_on": str(r.posted_on),
            })
        return out

    return guest_cached(viewer, "trending", produce, limit=limit)


@frappe.whitelist(allow_guest=True)
def get_profile_feed(user=None, slug=None, start=0, page_length=20):
    """Posts by a specific user that the viewer may see (by user or profile slug)."""
    viewer = get_viewer()
    if slug:
        user = frappe.db.get_value("Social Profile", {"profile_slug": slug}, "user")
    if not user:
        return []
    posts = _list_posts(
        viewer,
        {"is_deleted": 0, "author": user, "visibility": ("!=", "Group"), "page": ("is", "not set")},
        fields=POST_FIELDS,
        order_by="posted_on desc",
        start=cint(start),
        page_length=cint(page_length) or 20,
    )
    return enrich_posts(posts, viewer)


@frappe.whitelist(allow_guest=True)
def get_group_feed(group, start=0, page_length=20):
    """Posts within a group. Public groups are readable by anyone (including
    guests); Closed/Secret groups require membership."""
    viewer = get_viewer()
    privacy = frappe.db.get_value("Social Group", group, "privacy")
    if not privacy:
        frappe.throw(frappe._("Group not found."))
    if privacy == "Public":
        # Membership isn't required to read a public group, so bypass the
        # member-only row conditions with an explicit, scoped query.
        gfilters = {"is_deleted": 0, "group": group, "approval_status": "Approved",
                    "visibility": ("in", ["Group", "Public"])}
        blocked = get_block_ids(viewer)
        if blocked:
            gfilters["author"] = ("not in", list(blocked))
        posts = frappe.get_all(
            "Social Post",
            filters=gfilters,
            fields=POST_FIELDS,
            order_by="pinned desc, posted_on desc",
            start=cint(start),
            page_length=cint(page_length) or 20,
        )
        return enrich_posts(posts, viewer)
    if viewer == GUEST or group not in get_group_ids(viewer):
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
