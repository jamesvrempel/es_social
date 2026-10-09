# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Optional fan-out-on-write feed (ES Social Settings → Enable Fan-out Feed).

On publish, a background job writes a Social Feed Item into the inbox of
everyone who should see the post in their home feed: the author's friends
(Public/Connections posts), group members (Group posts) and page followers
(page posts). Accounts and pages above the celebrity threshold are NOT fanned
out — their posts are pulled at read time — so one big account can't create
thousands of rows per post. Inboxes are trimmed nightly to the configured cap.

With fan-out on, the member home feed becomes "friends, groups and pages you
follow" rather than "every post you're allowed to see". Guests and the
Trending sidebar are unaffected.
"""

import frappe
from frappe.utils import cint, now_datetime

from es_social.social.utils import get_connection_ids, get_settings


def enabled():
    """Write path: fan new posts out while the setting is on."""
    return bool(cint(get_settings().get("enable_fanout")))


def read_enabled(viewer):
    """Read path: only serve the home feed from inboxes once the backfill has
    finished AND this member actually has inbox rows. Otherwise the caller
    falls back to the normal (pull) feed, so an unbuilt or empty inbox can
    never blank someone's feed."""
    if not enabled() or not get_settings().get("fanout_ready_since"):
        return False
    return bool(frappe.db.exists("Social Feed Item", {"user": viewer}))


def _threshold():
    return cint(get_settings().get("fanout_celebrity_threshold") or 500)


def is_celebrity_author(user):
    return cint(frappe.db.get_value("Social Profile", {"user": user}, "connection_count")) > _threshold()


def is_celebrity_page(page):
    return cint(frappe.db.get_value("Social Page", page, "follower_count")) > _threshold()


def on_post_published(post_name):
    if enabled():
        frappe.enqueue("es_social.social.fanout.fanout_post", post=post_name,
                       queue="short", enqueue_after_commit=True)


def recipients_for(post):
    if post.visibility == "Only Me":
        return {post.author}
    if post.page:
        if is_celebrity_page(post.page):
            return {post.author}
        users = set(frappe.get_all("Social Page Follower", filters={"page": post.page}, pluck="user"))
    elif post.visibility == "Group" and post.group:
        users = set(frappe.get_all("Social Group Member",
                                   filters={"group": post.group, "status": "Active"}, pluck="user"))
    else:
        if is_celebrity_author(post.author):
            return {post.author}
        users = set(get_connection_ids(post.author))
    users.add(post.author)
    return users


def fanout_post(post):
    p = frappe.db.get_value("Social Post", post,
                            ["name", "author", "visibility", "group", "page", "posted_on",
                             "is_deleted", "approval_status"], as_dict=True)
    if not p or p.is_deleted or (p.approval_status or "Approved") != "Approved":
        return 0
    existing = set(frappe.get_all("Social Feed Item", filters={"post": p.name}, pluck="user"))
    n = 0
    for u in recipients_for(p) - existing:
        frappe.get_doc({"doctype": "Social Feed Item", "user": u, "post": p.name,
                        "author": p.author, "created_on": p.posted_on or now_datetime()
                        }).db_insert()
        n += 1
    frappe.db.commit()
    return n


def read_inbox(viewer, start, page_length):
    """Post names for the viewer's home feed from the inbox + celebrity pulls."""
    names = frappe.get_all("Social Feed Item", filters={"user": viewer},
                           fields=["post", "created_on"], order_by="created_on desc",
                           start=start, page_length=page_length)
    pulled = []
    oldest = names[-1].created_on if len(names) == page_length else None
    celebs = [u for u in get_connection_ids(viewer) if is_celebrity_author(u)]
    pages = [pg for pg in frappe.get_all("Social Page Follower", filters={"user": viewer}, pluck="page")
             if is_celebrity_page(pg)]
    if celebs or pages:
        filters = {"is_deleted": 0}
        if oldest:
            filters["posted_on"] = (">=", oldest)
        rows = []
        if celebs:
            rows += frappe.get_list("Social Post", filters=dict(filters, author=("in", celebs), page=("is", "not set")),
                                    fields=["name", "posted_on"], page_length=page_length)
        if pages:
            rows += frappe.get_list("Social Post", filters=dict(filters, page=("in", pages)),
                                    fields=["name", "posted_on"], page_length=page_length)
        pulled = [(r.name, r.posted_on) for r in rows]
    merged = {n.post: n.created_on for n in names}
    for name, ts in pulled:
        merged.setdefault(name, ts)
    return [k for k, _ in sorted(merged.items(), key=lambda kv: kv[1], reverse=True)]


def trim_inboxes():
    """Nightly: keep only the newest N items per inbox."""
    cap = cint(get_settings().get("feed_inbox_cap") or 500)
    frappe.db.sql(
        """delete fi from `tabSocial Feed Item` fi
           join (select name from (
                   select name, row_number() over (partition by `user` order by created_on desc) rn
                   from `tabSocial Feed Item`) ranked
                 where rn > %s) old on old.name = fi.name""",
        (cap,))
    frappe.db.commit()


def backfill(days=14):
    """`bench --site <site> execute es_social.social.fanout.backfill` after enabling."""
    since = frappe.utils.add_days(now_datetime(), -int(days))
    posts = frappe.get_all("Social Post", filters={"posted_on": (">=", since), "is_deleted": 0},
                           pluck="name", order_by="posted_on asc")
    total = sum(fanout_post(p) for p in posts)
    frappe.db.set_single_value("ES Social Settings", "fanout_ready_since", now_datetime())
    frappe.db.commit()
    frappe.clear_document_cache("ES Social Settings", "ES Social Settings")
    print(f"Fanned out {len(posts)} posts into {total} feed items.")
