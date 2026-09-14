# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Friend/connection graph."""

import frappe
from frappe.utils import now_datetime

from es_social.social.utils import (
    require_login, pair_key, get_connection_ids, clear_connection_cache, notify,
)
from es_social.api.feed import _author_map


@frappe.whitelist()
def send_request(to_user):
    viewer = require_login()
    if to_user == viewer:
        frappe.throw(frappe._("You cannot connect with yourself."))
    if not frappe.db.exists("User", to_user):
        frappe.throw(frappe._("No such user."))

    pk = pair_key(viewer, to_user)
    existing = frappe.db.get_value("Social Connection", {"pair_key": pk},
                                   ["name", "status", "from_user"], as_dict=True)
    if existing:
        if existing.status == "Accepted":
            return {"status": "Accepted", "name": existing.name}
        if existing.status == "Pending":
            return {"status": "Pending", "name": existing.name}
        # previously declined/blocked -> reopen
        frappe.db.set_value("Social Connection", existing.name,
                            {"from_user": viewer, "to_user": to_user,
                             "status": "Pending", "requested_on": now_datetime()})
        return {"status": "Pending", "name": existing.name}

    doc = frappe.get_doc({
        "doctype": "Social Connection",
        "from_user": viewer, "to_user": to_user, "status": "Pending",
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"status": "Pending", "name": doc.name}


@frappe.whitelist()
def respond_request(name, action):
    """action: 'accept' or 'decline'."""
    viewer = require_login()
    doc = frappe.get_doc("Social Connection", name)
    if doc.to_user != viewer:
        frappe.throw(frappe._("This request isn't addressed to you."), frappe.PermissionError)
    if action == "accept":
        doc.status = "Accepted"
        doc.responded_on = now_datetime()
        doc.save(ignore_permissions=True)
    elif action == "decline":
        doc.status = "Declined"
        doc.responded_on = now_datetime()
        doc.save(ignore_permissions=True)
    else:
        frappe.throw(frappe._("Unknown action."))
    frappe.db.commit()
    return {"status": doc.status}


@frappe.whitelist()
def unfriend(other_user):
    viewer = require_login()
    pk = pair_key(viewer, other_user)
    name = frappe.db.get_value("Social Connection", {"pair_key": pk}, "name")
    if name:
        frappe.delete_doc("Social Connection", name, ignore_permissions=True)
        clear_connection_cache(viewer, other_user)
        frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def block(other_user):
    viewer = require_login()
    pk = pair_key(viewer, other_user)
    existing = frappe.db.get_value("Social Connection", {"pair_key": pk}, "name")
    if existing:
        frappe.db.set_value("Social Connection", existing,
                            {"status": "Blocked", "from_user": viewer, "to_user": other_user})
    else:
        frappe.get_doc({"doctype": "Social Connection", "from_user": viewer,
                        "to_user": other_user, "status": "Blocked"}).insert(ignore_permissions=True)
    clear_connection_cache(viewer, other_user)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def list_connections(user=None):
    viewer = require_login()
    user = user or viewer
    ids = get_connection_ids(user)
    if not ids:
        return []
    authors = _author_map(ids)
    return [
        {"user": u, "display_name": a.display_name, "profile_image": a.profile_image,
         "profile_slug": a.profile_slug}
        for u, a in authors.items()
    ]


@frappe.whitelist()
def pending_requests():
    """Incoming requests awaiting the viewer's response."""
    viewer = require_login()
    rows = frappe.get_all("Social Connection",
                          filters={"to_user": viewer, "status": "Pending"},
                          fields=["name", "from_user", "requested_on"])
    authors = _author_map({r.from_user for r in rows})
    for r in rows:
        a = authors.get(r.from_user)
        r["display_name"] = a.display_name if a else r.from_user
        r["profile_image"] = a.profile_image if a else None
        r["requested_on"] = str(r.requested_on)
    return rows


@frappe.whitelist()
def connection_status(other_user):
    viewer = require_login()
    if other_user == viewer:
        return {"status": "self"}
    pk = pair_key(viewer, other_user)
    row = frappe.db.get_value("Social Connection", {"pair_key": pk},
                              ["status", "from_user", "name"], as_dict=True)
    if not row:
        return {"status": "none"}
    if row.status == "Pending":
        return {"status": "incoming" if row.from_user == other_user else "outgoing",
                "name": row.name}
    return {"status": row.status.lower(), "name": row.name}
