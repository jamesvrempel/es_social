# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Profile read/update + people & group search."""

import frappe

from es_social.social.utils import (
    GUEST, require_login, get_viewer, get_or_create_profile, scrub_for_guest,
)

EDITABLE = {
    "display_name", "headline", "bio", "location", "hometown", "website",
    "birthday", "gender", "relationship_status", "default_visibility",
    "profile_image", "cover_image",
}


@frappe.whitelist(allow_guest=True)
def get_profile(user=None, slug=None):
    viewer = get_viewer()
    name = None
    if slug:
        name = frappe.db.get_value("Social Profile", {"profile_slug": slug}, "name")
    elif viewer == GUEST:
        name = None  # guests look profiles up by their public slug only
    elif user:
        name = frappe.db.get_value("Social Profile", {"user": user}, "name")
    else:
        prof = get_or_create_profile(viewer)
        name = prof.name if prof else None
    if not name:
        frappe.throw(frappe._("Profile not found."))

    doc = frappe.get_doc("Social Profile", name)
    data = doc.get_public_dict()
    if viewer == GUEST:
        # public card only: no email, no work/education history
        data["is_self"] = False
        data["connection"] = {"status": "guest"}
        return scrub_for_guest(data, viewer)
    data["work"] = [w.as_dict() for w in doc.work]
    data["education"] = [e.as_dict() for e in doc.education]
    data["is_self"] = (doc.user == viewer)

    from es_social.api.connections import connection_status
    if not data["is_self"]:
        from es_social.social.moderation import is_blocked
        data["connection"] = connection_status(doc.user)
        data["blocked"] = is_blocked(viewer, doc.user)
        data["i_blocked"] = bool(frappe.db.exists("Social Block", {"blocker": viewer, "blocked": doc.user}))
        if data["blocked"]:
            # blocked either way: identity card only
            for f in ("work", "education", "bio", "location", "website"):
                data.pop(f, None)
    else:
        data["allow_messages_from"] = doc.get("allow_messages_from") or "Connections"
    return data


@frappe.whitelist()
def update_profile(**kwargs):
    viewer = require_login()
    prof = get_or_create_profile(viewer)
    changed = False
    for field, value in kwargs.items():
        if field in EDITABLE:
            setattr(prof, field, value)
            changed = True
    if changed:
        prof.save(ignore_permissions=True)
        frappe.db.commit()
    return prof.get_public_dict()


@frappe.whitelist(allow_guest=True)
def search_people(query, limit=15):
    viewer = get_viewer()
    limit = min(int(limit or 15), 25)
    if not query or len(query) < 2:
        return []
    like = f"%{query}%"
    rows = frappe.db.sql(
        """
        select user, display_name, profile_image, profile_slug, headline
        from `tabSocial Profile`
        where display_name like %(q)s or headline like %(q)s or location like %(q)s
        order by connection_count desc
        limit %(l)s
        """,
        {"q": like, "l": int(limit)}, as_dict=True,
    )
    return [scrub_for_guest(r, viewer) for r in rows]
