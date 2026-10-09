# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Group lifecycle & membership."""

import frappe
from frappe.utils import now_datetime

from es_social.social.utils import (
    GUEST, require_login, get_viewer, get_group_ids, get_member_role, get_settings,
    scrub_for_guest,
)


def _guard_groups_enabled():
    if not get_settings().enable_groups:
        frappe.throw(frappe._("Groups are disabled on this site."))


@frappe.whitelist()
def create_group(group_name, description=None, privacy="Public", join_policy="Open",
                 cover_image=None):
    viewer = require_login()
    _guard_groups_enabled()
    doc = frappe.get_doc({
        "doctype": "Social Group",
        "group_name": group_name,
        "description": description,
        "privacy": privacy,
        "join_policy": join_policy,
        "cover_image": cover_image,
        "created_by": viewer,
    })
    doc.insert()
    frappe.db.commit()
    return {"name": doc.name, "slug": doc.slug}


@frappe.whitelist()
def join_group(group):
    viewer = require_login()
    _guard_groups_enabled()
    if group in get_group_ids(viewer):
        return {"status": "Active"}
    policy = frappe.db.get_value("Social Group", group, "join_policy")
    status = "Active" if policy == "Open" else "Pending"
    existing = frappe.db.get_value("Social Group Member",
                                   {"group": group, "user": viewer}, ["name", "status"], as_dict=True)
    if existing and existing.status == "Banned":
        frappe.throw(frappe._("You can't join this group."), frappe.PermissionError)
    if existing:
        frappe.db.set_value("Social Group Member", existing.name, "status", status)
    else:
        frappe.get_doc({
            "doctype": "Social Group Member", "group": group, "user": viewer,
            "role": "Member", "status": status, "joined_on": now_datetime(),
        }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"status": status}


@frappe.whitelist()
def leave_group(group):
    viewer = require_login()
    if get_member_role(group, viewer) == "Admin" and frappe.db.count(
            "Social Group Member", {"group": group, "role": "Admin", "status": "Active"}) <= 1:
        frappe.throw(frappe._("You're the only admin. Make someone else an admin before leaving."))
    name = frappe.db.get_value("Social Group Member", {"group": group, "user": viewer}, "name")
    if name:
        frappe.delete_doc("Social Group Member", name, ignore_permissions=True)
        frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def approve_member(member):
    viewer = require_login()
    m = frappe.get_doc("Social Group Member", member)
    if get_member_role(m.group, viewer) not in ("Admin", "Moderator") \
            and not _is_privileged(viewer):
        frappe.throw(frappe._("Only group admins can approve members."), frappe.PermissionError)
    m.status = "Active"
    m.save(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist(allow_guest=True)
def list_my_groups():
    viewer = get_viewer()
    if viewer == GUEST:
        return []
    rows = frappe.get_all(
        "Social Group Member",
        filters={"user": viewer, "status": "Active"},
        fields=["group", "role"],
    )
    out = []
    for r in rows:
        g = frappe.db.get_value("Social Group", r.group,
                                ["group_name", "slug", "privacy", "member_count", "cover_image"],
                                as_dict=True)
        if g:
            g["role"] = r.role
            g["name"] = r.group
            out.append(g)
    return out


@frappe.whitelist(allow_guest=True)
def discover_groups(query=None, start=0, page_length=20):
    """Public + Closed groups (Secret groups are never listed)."""
    get_viewer()
    filters = {"privacy": ("in", ["Public", "Closed"])}
    if query:
        filters["group_name"] = ("like", f"%{query}%")
    return frappe.get_all(
        "Social Group", filters=filters,
        fields=["name", "group_name", "slug", "privacy", "member_count", "cover_image", "description"],
        order_by="member_count desc",
        start=int(start), page_length=int(page_length),
    )


@frappe.whitelist(allow_guest=True)
def get_group(group):
    viewer = get_viewer()
    g = frappe.db.get_value("Social Group", group,
                            ["name", "group_name", "slug", "privacy", "join_policy",
                             "member_count", "cover_image", "description", "created_by",
                             "rules", "post_approval"],
                            as_dict=True)
    if not g:
        frappe.throw(frappe._("Group not found."))
    if viewer == GUEST:
        if g["privacy"] == "Secret":
            frappe.throw(frappe._("Group not found."))
        g["my_role"] = None
        g["is_member"] = False
        return scrub_for_guest(g, viewer)
    g["my_role"] = get_member_role(group, viewer)
    g["is_member"] = group in get_group_ids(viewer)
    g["can_admin"] = g["my_role"] in ("Admin", "Moderator") or _is_privileged(viewer)
    if g["can_admin"]:
        g["pending_members"] = frappe.db.count("Social Group Member", {"group": group, "status": "Pending"})
        g["pending_posts"] = frappe.db.count("Social Post", {"group": group, "approval_status": "Pending",
                                                               "is_deleted": 0})
    g["my_status"] = frappe.db.get_value("Social Group Member", {"group": group, "user": viewer}, "status")
    if g["privacy"] == "Secret" and not g["is_member"] and not _is_privileged(viewer):
        frappe.throw(frappe._("Group not found."))
    return g


def _is_privileged(user):
    return bool({"System Manager", "Social Moderator", "Social Admin"} & set(frappe.get_roles(user)))
