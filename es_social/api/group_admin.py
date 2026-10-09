# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Group administration: members & roles, bans, settings, pins, invite links."""

import frappe
from frappe.utils import add_days, cint, get_datetime, now_datetime

from es_social.social.moderation import can_moderate_group, is_privileged, log_action
from es_social.social.utils import (
    get_group_ids, get_member_role, get_viewer, notify, require_login, GUEST,
)

PRIVACY_ORDER = {"Secret": 0, "Closed": 1, "Public": 2}


def _require_admin(group, user, allow_moderator=False):
    role = get_member_role(group, user)
    ok = role == "Admin" or (allow_moderator and role == "Moderator") or is_privileged(user)
    if not ok:
        frappe.throw(frappe._("Group admins only."), frappe.PermissionError)
    return role


def _member(group, user):
    name = frappe.db.get_value("Social Group Member", {"group": group, "user": user}, "name")
    if not name:
        frappe.throw(frappe._("That person isn't in this group."))
    return frappe.get_doc("Social Group Member", name)


def _admin_count(group):
    return frappe.db.count("Social Group Member", {"group": group, "role": "Admin", "status": "Active"})


@frappe.whitelist(allow_guest=True)
def list_members(group, status="Active", start=0, page_length=100):
    """Active members are listed to anyone who can see the group; Pending and
    Banned lists are for group admins/moderators."""
    viewer = get_viewer()
    privacy = frappe.db.get_value("Social Group", group, "privacy")
    if not privacy:
        frappe.throw(frappe._("Group not found."))
    if status != "Active":
        if viewer == GUEST or not can_moderate_group(group, viewer):
            frappe.throw(frappe._("Group admins only."), frappe.PermissionError)
    elif privacy != "Public" and (viewer == GUEST or group not in get_group_ids(viewer)) \
            and not is_privileged(viewer):
        frappe.throw(frappe._("Members only."), frappe.PermissionError)
    rows = frappe.get_all("Social Group Member",
                          filters={"group": group, "status": status if status in ("Active", "Pending", "Banned") else "Active"},
                          fields=["name", "user", "role", "status", "joined_on"],
                          order_by="field(role,'Admin','Moderator','Member'), joined_on asc",
                          start=cint(start), page_length=min(cint(page_length) or 100, 500))
    profiles = {p.user: p for p in frappe.get_all(
        "Social Profile", filters={"user": ("in", [r.user for r in rows] or ["__none__"])},
        fields=["user", "display_name", "profile_slug", "profile_image"])}
    out = []
    for r in rows:
        p = profiles.get(r.user)
        d = {"member": r.name, "role": r.role, "status": r.status, "joined_on": str(r.joined_on or ""),
             "display_name": p.display_name if p else "Member",
             "profile_slug": p.profile_slug if p else None,
             "profile_image": p.profile_image if p else None}
        if viewer != GUEST:
            d["user"] = r.user
        out.append(d)
    return out


@frappe.whitelist()
def set_role(group, user, role):
    viewer = require_login()
    _require_admin(group, viewer)
    if role not in ("Admin", "Moderator", "Member"):
        frappe.throw(frappe._("Unknown role."))
    m = _member(group, user)
    if m.status != "Active":
        frappe.throw(frappe._("Only active members can be given a role."))
    if m.role == "Admin" and role != "Admin" and _admin_count(group) <= 1:
        frappe.throw(frappe._("A group needs at least one admin."))
    m.role = role
    m.save(ignore_permissions=True)
    gname = frappe.db.get_value("Social Group", group, "group_name")
    notify(user, frappe._("You're now a {0} of {1}").format(role.lower(), gname),
           reference_doctype="Social Group", reference_name=group, link=f"/social/group/{group}")
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def remove_member(group, user):
    viewer = require_login()
    my_role = _require_admin(group, viewer, allow_moderator=True)
    m = _member(group, user)
    if m.role == "Admin" and my_role != "Admin" and not is_privileged(viewer):
        frappe.throw(frappe._("Moderators can't remove admins."), frappe.PermissionError)
    if m.role == "Admin" and _admin_count(group) <= 1:
        frappe.throw(frappe._("A group needs at least one admin."))
    frappe.delete_doc("Social Group Member", m.name, ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def ban_member(group, user, notes=None):
    viewer = require_login()
    my_role = _require_admin(group, viewer, allow_moderator=True)
    m = frappe.db.get_value("Social Group Member", {"group": group, "user": user}, ["name", "role"], as_dict=True)
    if m and m.role == "Admin" and my_role != "Admin" and not is_privileged(viewer):
        frappe.throw(frappe._("Moderators can't ban admins."), frappe.PermissionError)
    from es_social.api.moderation import _ban
    _ban(group, user, viewer)
    log_action("Ban From Group", user, "Social Group", group, notes=notes, moderator=viewer)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def unban_member(group, user):
    viewer = require_login()
    _require_admin(group, viewer, allow_moderator=True)
    m = _member(group, user)
    if m.status == "Banned":
        frappe.delete_doc("Social Group Member", m.name, ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def reject_member(member):
    viewer = require_login()
    m = frappe.get_doc("Social Group Member", member)
    _require_admin(m.group, viewer, allow_moderator=True)
    if m.status == "Pending":
        frappe.delete_doc("Social Group Member", m.name, ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def update_group(group, description=None, rules=None, cover_image=None, privacy=None,
                 join_policy=None, post_approval=None, confirm_widen=0):
    """Edit group settings. Making a group *more* visible (Secret→Closed→Public)
    exposes posts members wrote for a smaller audience, so it needs explicit
    confirmation; making it more private is always allowed."""
    viewer = require_login()
    _require_admin(group, viewer)
    g = frappe.get_doc("Social Group", group)
    if privacy and privacy != g.privacy:
        if privacy not in PRIVACY_ORDER:
            frappe.throw(frappe._("Unknown privacy setting."))
        if PRIVACY_ORDER[privacy] > PRIVACY_ORDER.get(g.privacy, 0) and not cint(confirm_widen):
            return {"ok": False, "needs_confirmation": True,
                    "message": frappe._("Changing to {0} makes existing posts visible to more people, "
                                        "including posts members wrote for the smaller audience.").format(privacy)}
        g.privacy = privacy
    for field, value in (("description", description), ("rules", rules), ("cover_image", cover_image)):
        if value is not None:
            g.set(field, value)
    if join_policy in ("Open", "Approval Required"):
        g.join_policy = join_policy
    if post_approval is not None:
        g.post_approval = cint(post_approval)
    g.save(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def pin_post(post, pinned=1):
    viewer = require_login()
    group = frappe.db.get_value("Social Post", post, "group")
    if not group:
        frappe.throw(frappe._("Only group posts can be pinned."))
    _require_admin(group, viewer, allow_moderator=True)
    frappe.db.set_value("Social Post", post, "pinned", 1 if cint(pinned) else 0)
    frappe.db.commit()
    return {"ok": True, "pinned": bool(cint(pinned))}


@frappe.whitelist()
def create_invite(group, days=7, max_uses=0):
    viewer = require_login()
    _require_admin(group, viewer, allow_moderator=True)
    token = frappe.generate_hash(length=24)
    days = cint(days)
    frappe.get_doc({
        "doctype": "Social Group Invite", "group": group, "token": token, "created_by": viewer,
        "expires_on": add_days(now_datetime(), days) if days > 0 else None,
        "max_uses": max(cint(max_uses), 0),
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"token": token, "url": f"/social/group/{group}?invite={token}"}


@frappe.whitelist()
def list_invites(group):
    viewer = require_login()
    _require_admin(group, viewer, allow_moderator=True)
    return frappe.get_all("Social Group Invite", filters={"group": group, "disabled": 0},
                          fields=["name", "token", "expires_on", "max_uses", "use_count"],
                          order_by="creation desc")


@frappe.whitelist()
def revoke_invite(name):
    viewer = require_login()
    group = frappe.db.get_value("Social Group Invite", name, "group")
    _require_admin(group, viewer, allow_moderator=True)
    frappe.db.set_value("Social Group Invite", name, "disabled", 1)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def join_by_invite(token):
    """Invite links skip the join request (but never a ban)."""
    viewer = require_login()
    inv = frappe.db.get_value("Social Group Invite", {"token": token, "disabled": 0},
                              ["name", "group", "expires_on", "max_uses", "use_count"], as_dict=True)
    if not inv:
        frappe.throw(frappe._("This invite link is invalid or has been revoked."))
    if inv.expires_on and get_datetime(inv.expires_on) < now_datetime():
        frappe.throw(frappe._("This invite link has expired."))
    if cint(inv.max_uses) and cint(inv.use_count) >= cint(inv.max_uses):
        frappe.throw(frappe._("This invite link has been used up."))
    existing = frappe.db.get_value("Social Group Member", {"group": inv.group, "user": viewer},
                                   ["name", "status"], as_dict=True)
    if existing and existing.status == "Banned":
        frappe.throw(frappe._("You can't join this group."), frappe.PermissionError)
    if existing and existing.status == "Active":
        return {"ok": True, "group": inv.group}
    if existing:
        m = frappe.get_doc("Social Group Member", existing.name)
        m.status = "Active"
        m.save(ignore_permissions=True)
    else:
        frappe.get_doc({"doctype": "Social Group Member", "group": inv.group, "user": viewer,
                        "role": "Member", "status": "Active", "joined_on": now_datetime()
                        }).insert(ignore_permissions=True)
    frappe.db.sql("update `tabSocial Group Invite` set use_count = use_count + 1 where name=%s", inv.name)
    frappe.db.commit()
    return {"ok": True, "group": inv.group}
