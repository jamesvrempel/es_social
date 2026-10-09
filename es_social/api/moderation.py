# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Moderation queue & actions.

Site moderators (Social Moderator / Social Admin / System Manager) see every
report. Group admins & moderators see reports and pending posts for their own
groups only. Every action is written to the Social Moderation Log.
"""

import frappe
from frappe.utils import add_days, cint, now_datetime

from es_social.social.moderation import (
    can_moderate_group, clear_block_cache, content_owner, is_privileged,
    log_action, set_content_hidden,
)
from es_social.social.utils import get_member_role, notify, require_login

ACTIONS = ("hide", "restore", "dismiss", "warn", "suspend", "ban_from_group")


def _my_mod_groups(user):
    return frappe.get_all("Social Group Member",
                          filters={"user": user, "status": "Active", "role": ("in", ["Admin", "Moderator"])},
                          pluck="group")


def _require_moderator():
    user = require_login()
    if not is_privileged(user) and not _my_mod_groups(user):
        frappe.throw(frappe._("Moderators only."), frappe.PermissionError)
    return user


def _preview(doctype, name):
    if doctype == "Social Post":
        r = frappe.db.get_value("Social Post", name, ["content", "is_deleted", "group", "approval_status"], as_dict=True)
        return r and {"text": frappe.utils.strip_html(r.content or "")[:400], "hidden": bool(r.is_deleted),
                      "url": f"/social/group/{r.group}" if r.group else "/social", "pending": r.approval_status == "Pending"}
    if doctype == "Social Comment":
        r = frappe.db.get_value("Social Comment", name, ["content", "is_deleted"], as_dict=True)
        return r and {"text": frappe.utils.strip_html(r.content or "")[:400], "hidden": bool(r.is_deleted)}
    if doctype == "Social Message":
        r = frappe.db.get_value("Social Message", name, ["content", "is_deleted"], as_dict=True)
        return r and {"text": (r.content or "")[:400], "hidden": bool(r.is_deleted)}
    if doctype == "Social Page":
        r = frappe.db.get_value("Social Page", name, ["page_name", "slug"], as_dict=True)
        return r and {"text": r.page_name, "url": f"/p/{r.slug}"}
    if doctype == "User":
        r = frappe.db.get_value("Social Profile", {"user": name}, ["display_name", "profile_slug"], as_dict=True)
        return r and {"text": r.display_name, "url": f"/u/{r.profile_slug}"}
    return None


@frappe.whitelist()
def get_queue(status="Open", group=None, start=0, page_length=30):
    """Reports grouped by item (one row per reported item, with counts)."""
    user = _require_moderator()
    filters = {"status": status if status in ("Open", "Reviewed", "Actioned", "Dismissed") else "Open"}
    if group:
        if not can_moderate_group(group, user):
            frappe.throw(frappe._("Not allowed."), frappe.PermissionError)
        filters["group"] = group
    elif not is_privileged(user):
        groups = _my_mod_groups(user)
        filters["group"] = ("in", groups or ["__none__"])
    reports = frappe.get_all("Social Report", filters=filters,
                             fields=["name", "reference_doctype", "reference_name", "reason",
                                     "reported_by", "reported_user", "group", "details", "creation"],
                             order_by="creation asc", limit_page_length=1000)
    items = {}
    for r in reports:
        k = (r.reference_doctype, r.reference_name)
        it = items.setdefault(k, {"reference_doctype": r.reference_doctype, "reference_name": r.reference_name,
                                  "reported_user": r.reported_user, "group": r.group, "reports": [],
                                  "first_reported": str(r.creation), "reasons": {}})
        it["reports"].append(r.name)
        it["reasons"][r.reason] = it["reasons"].get(r.reason, 0) + 1
        if r.details and len(it.get("details", [])) < 3:
            it.setdefault("details", []).append(r.details[:200])
    out = sorted(items.values(), key=lambda i: (-len(i["reports"]), i["first_reported"]))
    start, page_length = cint(start), cint(page_length) or 30
    out = out[start:start + page_length]
    names = {i["reported_user"] for i in out if i["reported_user"]}
    profiles = {p.user: p for p in frappe.get_all("Social Profile", filters={"user": ("in", list(names))},
                                                  fields=["user", "display_name", "profile_slug", "suspended"])} if names else {}
    for i in out:
        i["preview"] = _preview(i["reference_doctype"], i["reference_name"])
        p = profiles.get(i["reported_user"])
        i["reported_user_name"] = p.display_name if p else i["reported_user"]
        i["reported_user_slug"] = p.profile_slug if p else None
        i["reported_user_suspended"] = bool(p and p.suspended)
        i["count"] = len(i["reports"])
    return out


@frappe.whitelist()
def act(reference_doctype, reference_name, action, notes=None, days=None):
    """Resolve every open report on an item with one action.

    hide | restore | dismiss | warn | suspend (site moderators; days blank =
    until lifted) | ban_from_group (group admins for content in their group).
    """
    user = _require_moderator()
    if action not in ACTIONS:
        frappe.throw(frappe._("Unknown action."))
    owner = content_owner(reference_doctype, reference_name)
    from es_social.social.moderation import content_group
    group = content_group(reference_doctype, reference_name)
    site_mod = is_privileged(user)
    if not site_mod and not (group and can_moderate_group(group, user)):
        frappe.throw(frappe._("Not allowed."), frappe.PermissionError)

    reports = frappe.get_all("Social Report", filters={"reference_doctype": reference_doctype,
                                                        "reference_name": reference_name, "status": "Open"},
                             pluck="name")
    first_report = reports[0] if reports else None
    status = "Actioned"

    if action == "hide":
        set_content_hidden(reference_doctype, reference_name, True)
        log_action("Hide Content", owner, reference_doctype, reference_name, first_report, notes)
    elif action == "restore":
        set_content_hidden(reference_doctype, reference_name, False)
        if reference_doctype == "Social Post":
            frappe.db.set_value("Social Post", reference_name, "approval_status", "Approved")
        log_action("Restore Content", owner, reference_doctype, reference_name, first_report, notes)
        status = "Reviewed"
    elif action == "dismiss":
        log_action("Dismiss Report", owner, reference_doctype, reference_name, first_report, notes)
        status = "Dismissed"
    elif action == "warn":
        notify(owner, frappe._("A moderator reviewed your content: please follow the community guidelines."),
               message=notes or "", reference_doctype=reference_doctype if reference_doctype != "User" else None,
               reference_name=reference_name if reference_doctype != "User" else None)
        log_action("Warn User", owner, reference_doctype, reference_name, first_report, notes)
    elif action == "suspend":
        if not site_mod:
            frappe.throw(frappe._("Only site moderators can suspend accounts."), frappe.PermissionError)
        suspend(owner, days=days, reason=notes, _report=first_report)
    elif action == "ban_from_group":
        if not group:
            frappe.throw(frappe._("This content isn't in a group."))
        _ban(group, owner, user)
        set_content_hidden(reference_doctype, reference_name, True)
        log_action("Ban From Group", owner, "Social Group", group, first_report, notes)

    for r in reports:
        frappe.db.set_value("Social Report", r, "status", status)
    frappe.db.commit()
    return {"ok": True, "resolved": len(reports)}


@frappe.whitelist()
def suspend(user, days=None, reason=None, _report=None):
    mod = require_login()
    if not is_privileged(mod):
        frappe.throw(frappe._("Only site moderators can suspend accounts."), frappe.PermissionError)
    if is_privileged(user):
        frappe.throw(frappe._("Moderator accounts can't be suspended here."))
    prof = frappe.db.get_value("Social Profile", {"user": user}, "name")
    if not prof:
        from es_social.social.utils import get_or_create_profile
        prof = get_or_create_profile(user).name
    until = add_days(now_datetime(), cint(days)) if cint(days) > 0 else None
    frappe.db.set_value("Social Profile", prof, {"suspended": 1, "suspended_until": until,
                                                 "suspension_reason": reason})
    log_action("Suspend User", user, "User", user, _report,
               (reason or "") + (f" ({cint(days)} days)" if until else " (until lifted)"), moderator=mod)
    from es_social.social.utils import brand_name
    notify(user, frappe._("Your {0} account has been suspended.").format(brand_name()), message=reason or "")
    frappe.db.commit()
    return {"ok": True, "until": str(until) if until else None}


@frappe.whitelist()
def unsuspend(user):
    mod = require_login()
    if not is_privileged(mod):
        frappe.throw(frappe._("Only site moderators can lift suspensions."), frappe.PermissionError)
    prof = frappe.db.get_value("Social Profile", {"user": user}, "name")
    if prof:
        frappe.db.set_value("Social Profile", prof, {"suspended": 0, "suspended_until": None,
                                                     "suspension_reason": None})
    log_action("Unsuspend User", user, "User", user, moderator=mod)
    frappe.db.commit()
    return {"ok": True}


def _ban(group, user, by):
    if get_member_role(group, user) == "Admin":
        frappe.throw(frappe._("Group admins can't be banned — demote them first."))
    name = frappe.db.get_value("Social Group Member", {"group": group, "user": user}, "name")
    if name:
        m = frappe.get_doc("Social Group Member", name)
        m.status, m.role = "Banned", "Member"
        m.save(ignore_permissions=True)
    else:
        frappe.get_doc({"doctype": "Social Group Member", "group": group, "user": user,
                        "role": "Member", "status": "Banned"}).insert(ignore_permissions=True)


# --------------------------------------------------------------------------- #
# Pending posts (group post approval + keyword holds)
# --------------------------------------------------------------------------- #

@frappe.whitelist()
def pending_posts(group=None):
    user = require_login()
    filters = {"approval_status": "Pending", "is_deleted": 0}
    if group:
        if not can_moderate_group(group, user):
            frappe.throw(frappe._("Not allowed."), frappe.PermissionError)
        filters["group"] = group
    elif not is_privileged(user):
        filters["group"] = ("in", _my_mod_groups(user) or ["__none__"])
    from es_social.api.feed import POST_FIELDS, enrich_posts
    rows = frappe.get_all("Social Post", filters=filters, fields=POST_FIELDS,
                          order_by="posted_on asc", page_length=100)
    return enrich_posts([dict(r) for r in rows], user)


@frappe.whitelist()
def review_post(post, decision, notes=None):
    """decision: approve | reject"""
    user = require_login()
    p = frappe.db.get_value("Social Post", post, ["name", "group", "author", "approval_status"], as_dict=True)
    if not p:
        frappe.throw(frappe._("Post not found."))
    if not (is_privileged(user) or (p.group and can_moderate_group(p.group, user))):
        frappe.throw(frappe._("Not allowed."), frappe.PermissionError)
    if decision == "approve":
        frappe.db.set_value("Social Post", post, "approval_status", "Approved")
        log_action("Approve Post", p.author, "Social Post", post, notes=notes, moderator=user)
        notify(p.author, frappe._("Your post was approved."), reference_doctype="Social Post", reference_name=post)
        from es_social.social.fanout import on_post_published
        on_post_published(post)
        status = "Reviewed"
    elif decision == "reject":
        frappe.db.set_value("Social Post", post, {"approval_status": "Rejected", "is_deleted": 1})
        log_action("Reject Post", p.author, "Social Post", post, notes=notes, moderator=user)
        notify(p.author, frappe._("Your post wasn't approved."), message=notes or "")
        status = "Actioned"
    else:
        frappe.throw(frappe._("Unknown decision."))
    for r in frappe.get_all("Social Report", filters={"reference_doctype": "Social Post",
                                                       "reference_name": post, "status": "Open"}, pluck="name"):
        frappe.db.set_value("Social Report", r, "status", status)
    frappe.db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Dashboard numbers (site moderators)
# --------------------------------------------------------------------------- #

@frappe.whitelist()
def stats():
    user = require_login()
    if not is_privileged(user):
        frappe.throw(frappe._("Site moderators only."), frappe.PermissionError)
    week = add_days(now_datetime(), -7)
    q = lambda sql, *a: frappe.db.sql(sql, a)[0][0] or 0  # noqa: E731
    return {
        "open_reports": q("select count(*) from `tabSocial Report` where status='Open'"),
        "open_items": q("select count(distinct reference_doctype, reference_name) from `tabSocial Report` where status='Open'"),
        "reports_7d": q("select count(*) from `tabSocial Report` where creation >= %s", week),
        "pending_posts": q("select count(*) from `tabSocial Post` where approval_status='Pending' and is_deleted=0"),
        "suspended": q("select count(*) from `tabSocial Profile` where suspended=1"),
        "avg_resolve_hours": round(float(q(
            """select avg(timestampdiff(minute, r.creation, r.modified))/60 from `tabSocial Report` r
               where r.status in ('Actioned','Dismissed','Reviewed') and r.modified >= %s""", week)), 1),
        "top_reported": frappe.db.sql(
            """select reported_user, count(*) c from `tabSocial Report`
               where creation >= %s and reported_user is not null and reported_user != ''
               group by reported_user order by c desc limit 5""", (week,), as_dict=True),
    }
