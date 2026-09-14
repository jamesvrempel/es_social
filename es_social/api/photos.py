# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Photo gallery — a user's images aggregated from their visible posts."""

import frappe
from frappe.utils import cint

from es_social.social.utils import require_login


@frappe.whitelist()
def get_photos(user=None, slug=None, start=0, page_length=60):
    """Return images from *user*'s posts that the viewer is allowed to see.

    permission_query_conditions on Social Post is applied automatically by
    frappe.get_list, so private/connections/group posts stay hidden from
    non-permitted viewers.
    """
    viewer = require_login()
    if slug:
        user = frappe.db.get_value("Social Profile", {"profile_slug": slug}, "user")
    user = user or viewer

    posts = frappe.get_list(
        "Social Post",
        filters={"is_deleted": 0, "author": user},
        fields=["name", "posted_on"],
        order_by="posted_on desc",
        start=cint(start),
        page_length=cint(page_length) or 60,
    )
    names = [p.name for p in posts]

    prof = frappe.db.get_value(
        "Social Profile", {"user": user}, ["display_name", "profile_slug"], as_dict=True
    )
    header = {
        "user": user,
        "display_name": prof.display_name if prof else user,
        "slug": prof.profile_slug if prof else None,
        "is_self": user == viewer,
    }

    if not names:
        header["photos"] = []
        return header

    order = {}
    i = 0
    for n in names:
        order[n] = i
        i += 1

    media = frappe.get_all(
        "Social Post Media",
        filters={"parent": ["in", names], "parenttype": "Social Post"},
        fields=["parent", "image", "caption", "sort_order"],
    )
    media.sort(key=lambda m: (order.get(m.parent, 0), m.sort_order or 0))

    photos = []
    for m in media:
        if m.image:
            photos.append({"image": m.image, "post": m.parent, "caption": m.caption})

    header["photos"] = photos
    return header
