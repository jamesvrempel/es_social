# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Trending + personalised ("Top") ranking.

trending score  = (reactions + 2*commenters + 3*shares + 1) / (age_hours + 2) ** GRAVITY
                  counting distinct people, never the author themselves.
personal score  = trending score * (1 + affinity(viewer, author)) [+ followed-page boost]

Affinity grows when a viewer reacts to (+1) or comments on (+2) an author's
posts and decays 10% a day, so it reflects recent relationships.
"""

import math

import frappe
from frappe.utils import add_days, cint, get_datetime, now_datetime

GRAVITY = 1.5
TRENDING_WINDOW_HOURS = 72
AFFINITY_DECAY = 0.9


def score(reactions, commenters, shares, age_hours):
    return (cint(reactions) + 2 * cint(commenters) + 3 * cint(shares) + 1) / math.pow(max(age_hours, 0) + 2, GRAVITY)


def _age_hours(posted_on):
    return (now_datetime() - get_datetime(posted_on)).total_seconds() / 3600.0


# --------------------------------------------------------------------------- #
# Trending (hourly job)
# --------------------------------------------------------------------------- #

def recompute_trending():
    from es_social.social.utils import get_settings
    min_days = cint(get_settings().get("trending_min_account_days") or 0)
    since = frappe.utils.add_to_date(now_datetime(), hours=-TRENDING_WINDOW_HOURS)
    rows = frappe.db.sql(
        """
        select p.name, p.author, p.posted_on, p.share_count, u.creation as author_since,
          (select count(*) from `tabSocial Reaction` r
            where r.reference_doctype='Social Post' and r.reference_name=p.name
              and r.user != p.author) as reactions,
          (select count(distinct c.author) from `tabSocial Comment` c
            where c.reference_post=p.name and c.is_deleted=0 and c.author != p.author) as commenters
        from `tabSocial Post` p
        left join `tabUser` u on u.name = p.author
        where p.posted_on >= %(since)s and p.is_deleted = 0
          and p.visibility = 'Public'
          and coalesce(p.approval_status, 'Approved') = 'Approved'
        """,
        {"since": since}, as_dict=True,
    )
    cutoff = add_days(now_datetime(), -min_days) if min_days else None
    for r in rows:
        s = score(r.reactions, r.commenters, r.share_count, _age_hours(r.posted_on))
        if cutoff and r.author_since and get_datetime(r.author_since) > cutoff:
            s = 0  # brand-new accounts can't push content into Trending
        frappe.db.set_value("Social Post", r.name, "score", round(s, 6), update_modified=False)
    # anything that has aged out of the window drops off Trending
    frappe.db.sql(
        "update `tabSocial Post` set score=0 where score > 0 and posted_on < %s", (since,))
    frappe.db.commit()


# --------------------------------------------------------------------------- #
# Affinity
# --------------------------------------------------------------------------- #

def bump_affinity(viewer, author, delta):
    """Best-effort upsert; called from reaction/comment after_insert."""
    if not viewer or not author or viewer == author or "Guest" in (viewer, author):
        return
    try:
        name = frappe.db.get_value("Social Affinity", {"user": viewer, "other_user": author}, "name")
        if name:
            frappe.db.sql(
                "update `tabSocial Affinity` set score = score + %s, updated_on = %s where name = %s",
                (delta, now_datetime(), name))
        else:
            frappe.get_doc({"doctype": "Social Affinity", "user": viewer, "other_user": author,
                            "score": delta, "updated_on": now_datetime()}).insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "es_social: affinity update failed")


def decay_affinity():
    """Daily: decay every affinity score and prune negligible ones."""
    frappe.db.sql("update `tabSocial Affinity` set score = score * %s", (AFFINITY_DECAY,))
    frappe.db.sql("delete from `tabSocial Affinity` where score < 0.05")
    frappe.db.commit()


def affinity_map(viewer, authors):
    if not authors or viewer == "Guest":
        return {}
    rows = frappe.get_all("Social Affinity",
                          filters={"user": viewer, "other_user": ("in", list(authors))},
                          fields=["other_user", "score"])
    return {r.other_user: r.score for r in rows}


def rank_personal(posts, viewer):
    """Re-rank a candidate list of post dicts for the viewer ("Top" sort)."""
    if not posts:
        return posts
    aff = affinity_map(viewer, {p["author"] for p in posts})
    followed = set()
    if viewer != "Guest":
        followed = set(frappe.get_all("Social Page Follower", filters={"user": viewer}, pluck="page"))

    def key(p):
        base = score(p.get("like_count"), p.get("comment_count"), p.get("share_count"),
                     _age_hours(p.get("posted_on")))
        boost = 1 + min(aff.get(p["author"], 0), 20) / 4.0
        if p.get("page") and p["page"] in followed:
            boost += 0.5
        return base * boost
    return sorted(posts, key=key, reverse=True)
