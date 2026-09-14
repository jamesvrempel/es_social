# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Profile read/update + people & group search."""

import frappe

from es_social.social.utils import require_login, get_or_create_profile

EDITABLE = {
    "display_name", "headline", "bio", "location", "hometown", "website",
    "birthday", "gender", "relationship_status", "default_visibility",
    "profile_image", "cover_image",
}


@frappe.whitelist()
def get_profile(user=None, slug=None):
    viewer = require_login()
    name = None
    if slug:
        name = frappe.db.get_value("Social Profile", {"profile_slug": slug}, "name")
    elif user:
        name = frappe.db.get_value("Social Profile", {"user": user}, "name")
    else:
        prof = get_or_create_profile(viewer)
        name = prof.name if prof else None
    if not name:
        frappe.throw(frappe._("Profile not found."))

    doc = frappe.get_doc("Social Profile", name)
    data = doc.get_public_dict()
    data["work"] = [w.as_dict() for w in doc.work]
    data["education"] = [e.as_dict() for e in doc.education]
    data["is_self"] = (doc.user == viewer)

    from es_social.api.connections import connection_status
    if not data["is_self"]:
        data["connection"] = connection_status(doc.user)
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


@frappe.whitelist()
def search_people(query, limit=15):
    require_login()
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
    return rows
