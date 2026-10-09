# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Moderation primitives shared by every phase: blocking, suspension, the
moderation audit log, report handling and auto-hide."""

import frappe
from frappe.utils import cint, get_datetime, now_datetime

PRIVILEGED = {"System Manager", "Social Moderator", "Social Admin", "Administrator"}
BLOCK_CACHE_TTL = 300


def is_privileged(user=None):
    user = user or frappe.session.user
    return user == "Administrator" or bool(PRIVILEGED & set(frappe.get_roles(user)))


# --------------------------------------------------------------------------- #
# Blocking
# --------------------------------------------------------------------------- #

def _block_key(user):
    return f"es_social:blocks:{user}"


def get_block_ids(user=None):
    """Users hidden from *user*: people they blocked AND people who blocked them.
    Blocking is symmetric for visibility and contact."""
    user = user or frappe.session.user
    if not user or user == "Guest":
        return set()
    cache = frappe.cache()
    cached = cache.get_value(_block_key(user))
    if cached is not None:
        return set(cached)
    rows = frappe.db.sql(
        """select blocked as u from `tabSocial Block` where blocker=%(u)s
           union select blocker as u from `tabSocial Block` where blocked=%(u)s""",
        {"u": user}, as_dict=True,
    )
    ids = sorted({r.u for r in rows if r.u})
    cache.set_value(_block_key(user), ids, expires_in_sec=BLOCK_CACHE_TTL)
    return set(ids)


def clear_block_cache(*users):
    for u in users:
        if u:
            frappe.cache().delete_value(_block_key(u))


def is_blocked(a, b):
    """True if either user has blocked the other."""
    if not a or not b or a == b or "Guest" in (a, b):
        return False
    return b in get_block_ids(a)


def assert_not_blocked(a, b, msg=None):
    if is_blocked(a, b):
        frappe.throw(msg or frappe._("You can't interact with this member."), frappe.PermissionError)


# --------------------------------------------------------------------------- #
# Suspension
# --------------------------------------------------------------------------- #

def is_suspended(user):
    if not user or user in ("Guest", "Administrator"):
        return False
    row = frappe.db.get_value("Social Profile", {"user": user},
                              ["name", "suspended", "suspended_until"], as_dict=True)
    if not row or not cint(row.suspended):
        return False
    if row.suspended_until and get_datetime(row.suspended_until) <= now_datetime():
        # expired — lift automatically
        frappe.db.set_value("Social Profile", row.name,
                            {"suspended": 0, "suspended_until": None, "suspension_reason": None},
                            update_modified=False)
        return False
    return True


def assert_not_suspended(user):
    if is_suspended(user):
        until = frappe.db.get_value("Social Profile", {"user": user}, "suspended_until")
        msg = frappe._("Your account is suspended")
        msg += (" " + frappe._("until {0}").format(frappe.format(until, "Datetime"))) if until else ""
        frappe.throw(msg + ".", frappe.PermissionError)


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #

def log_action(action, target_user=None, target_doctype=None, target_name=None,
               report=None, notes=None, moderator=None):
    try:
        frappe.get_doc({
            "doctype": "Social Moderation Log",
            "action": action,
            "moderator": moderator or frappe.session.user,
            "target_user": target_user,
            "target_doctype": target_doctype,
            "target_name": target_name,
            "report": report,
            "notes": notes,
        }).insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "es_social: moderation log failed")


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #

def content_owner(doctype, name):
    if doctype == "Social Post":
        return frappe.db.get_value("Social Post", name, "author")
    if doctype == "Social Comment":
        return frappe.db.get_value("Social Comment", name, "author")
    if doctype == "Social Message":
        return frappe.db.get_value("Social Message", name, "sender")
    if doctype == "Social Page":
        return frappe.db.get_value("Social Page", name, "created_by")
    if doctype == "User":
        return name
    return None


def content_group(doctype, name):
    if doctype == "Social Post":
        return frappe.db.get_value("Social Post", name, "group")
    if doctype == "Social Comment":
        post = frappe.db.get_value("Social Comment", name, "reference_post")
        return frappe.db.get_value("Social Post", post, "group") if post else None
    return None


def set_content_hidden(doctype, name, hidden=True):
    if doctype in ("Social Post", "Social Comment", "Social Message"):
        frappe.db.set_value(doctype, name, "is_deleted", 1 if hidden else 0)
        if doctype == "Social Comment":
            post = frappe.db.get_value("Social Comment", name, "reference_post")
            if post:
                from es_social.social.utils import bump
                bump("Social Post", post, "comment_count", -1 if hidden else 1)
        return True
    return False


def maybe_auto_hide(doctype, name):
    """Hide content once N distinct members have reported it (pending review)."""
    from es_social.social.utils import get_settings
    threshold = cint(get_settings().get("auto_hide_report_threshold"))
    if threshold <= 0 or doctype not in ("Social Post", "Social Comment", "Social Message"):
        return False
    reporters = frappe.db.sql(
        """select count(distinct reported_by) from `tabSocial Report`
           where reference_doctype=%s and reference_name=%s and status='Open'""",
        (doctype, name),
    )[0][0]
    if reporters >= threshold and not frappe.db.get_value(doctype, name, "is_deleted"):
        set_content_hidden(doctype, name, True)
        log_action("Auto-hide", target_user=content_owner(doctype, name),
                   target_doctype=doctype, target_name=name,
                   notes=f"{reporters} open reports", moderator="Administrator")
        return True
    return False


def queue_for_review(doctype, name, reason="Other", details=None):
    """System-raised report (e.g. keyword hold) so it lands in the moderation queue."""
    frappe.get_doc({
        "doctype": "Social Report",
        "reference_doctype": doctype,
        "reference_name": name,
        "reported_by": "Administrator",
        "reported_user": content_owner(doctype, name),
        "group": content_group(doctype, name),
        "reason": reason,
        "details": details,
        "status": "Open",
    }).insert(ignore_permissions=True)


def can_moderate_group(group, user=None):
    from es_social.social.utils import get_member_role
    user = user or frappe.session.user
    if is_privileged(user):
        return True
    return bool(group) and get_member_role(group, user) in ("Admin", "Moderator")
