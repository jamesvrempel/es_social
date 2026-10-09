# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""One-to-one direct messages (ES Social Settings → Enable Messaging).

Raven: if the Raven app is installed and Messaging Provider = Raven, the
"Message" button hands off to Raven instead and nothing here is used.

Privacy: conversations are readable only by their two participants. Site
moderators can't browse them; a *reported* message is shown to moderators on
its own, without the rest of the thread.
"""

import frappe
from frappe.utils import cint, get_datetime, now_datetime

from es_social.social.moderation import is_blocked
from es_social.social.utils import (
    GUEST, are_connected, check_content, enforce_rate_limit, get_settings, get_viewer,
    pair_key, require_login,
)

PAGE = 50


def _guard_enabled():
    if not cint(get_settings().get("enable_messaging")):
        frappe.throw(frappe._("Messaging is not enabled on this site."))


def _provider():
    if (get_settings().get("messaging_provider") or "Built-in") == "Raven" \
            and "raven" in frappe.get_installed_apps():
        return "Raven"
    return "Built-in"


def can_message(sender, recipient):
    if not recipient or sender == recipient or GUEST in (sender, recipient):
        return False
    if is_blocked(sender, recipient):
        return False
    pref = frappe.db.get_value("Social Profile", {"user": recipient}, "allow_messages_from") or "Connections"
    if pref == "Everyone":
        return True
    if pref == "No one":
        return False
    return are_connected(sender, recipient)


def _resolve(user=None, slug=None):
    if slug:
        user = frappe.db.get_value("Social Profile", {"profile_slug": slug}, "user")
    if not user or not frappe.db.exists("User", user):
        frappe.throw(frappe._("Member not found."))
    return user


def _conversation_for(viewer, conversation):
    c = frappe.db.get_value("Social Conversation", conversation,
                            ["name", "user_a", "user_b", "a_last_read", "b_last_read",
                             "last_message_at", "last_sender"], as_dict=True)
    if not c or viewer not in (c.user_a, c.user_b):
        frappe.throw(frappe._("Conversation not found."), frappe.PermissionError)
    c.other = c.user_b if viewer == c.user_a else c.user_a
    c.me_field = "a_last_read" if viewer == c.user_a else "b_last_read"
    return c


def message_participant(message, user):
    conv = frappe.db.get_value("Social Message", message, "conversation")
    if not conv:
        return False
    a, b = frappe.db.get_value("Social Conversation", conv, ["user_a", "user_b"]) or (None, None)
    return user in (a, b)


@frappe.whitelist()
def start_conversation(user=None, slug=None):
    """Open (or create) the thread with a member. In Raven mode returns a URL."""
    viewer = require_login()
    _guard_enabled()
    other = _resolve(user, slug)
    if _provider() == "Raven":
        return {"provider": "Raven", "url": _raven_url(other)}
    if not can_message(viewer, other):
        frappe.throw(frappe._("This member isn't accepting messages from you."), frappe.PermissionError)
    pk = pair_key(viewer, other)
    name = frappe.db.get_value("Social Conversation", {"pair_key": pk}, "name")
    if not name:
        a, b = sorted([viewer, other])
        name = frappe.get_doc({"doctype": "Social Conversation", "pair_key": pk,
                               "user_a": a, "user_b": b}).insert(ignore_permissions=True).name
        frappe.db.commit()
    return {"provider": "Built-in", "conversation": name}


def _raven_url(other):
    """Best-effort deep link into a Raven DM; falls back to the Raven home."""
    try:
        fn = frappe.get_attr("raven.api.raven_channel.create_direct_message_channel")
        channel = fn(other)
        return f"/raven/channel/{channel}"
    except Exception:
        return "/raven"


def _profiles(users):
    users = [u for u in users if u]
    if not users:
        return {}
    return {p.user: p for p in frappe.get_all(
        "Social Profile", filters={"user": ("in", users)},
        fields=["user", "display_name", "profile_slug", "profile_image"])}


@frappe.whitelist(allow_guest=True)
def list_conversations(start=0, page_length=30):
    viewer = get_viewer()
    if viewer == GUEST or not cint(get_settings().get("enable_messaging")):
        return []
    rows = frappe.db.sql(
        """select name, user_a, user_b, last_message, last_sender, last_message_at, a_last_read, b_last_read
           from `tabSocial Conversation`
           where (user_a=%(u)s or user_b=%(u)s) and last_message_at is not null
           order by last_message_at desc limit %(s)s, %(n)s""",
        {"u": viewer, "s": cint(start), "n": min(cint(page_length) or 30, 100)}, as_dict=True)
    others = [r.user_b if r.user_a == viewer else r.user_a for r in rows]
    profiles = _profiles(others)
    out = []
    for r, other in zip(rows, others):
        if is_blocked(viewer, other):
            continue
        my_read = r.a_last_read if r.user_a == viewer else r.b_last_read
        p = profiles.get(other)
        out.append({
            "conversation": r.name,
            "display_name": p.display_name if p else other,
            "profile_slug": p.profile_slug if p else None,
            "profile_image": p.profile_image if p else None,
            "last_message": (r.last_message or "")[:120],
            "last_message_at": str(r.last_message_at),
            "mine": r.last_sender == viewer,
            "unread": bool(r.last_sender != viewer and (not my_read or get_datetime(my_read) < get_datetime(r.last_message_at))),
        })
    return out


@frappe.whitelist()
def get_messages(conversation, before=None, limit=PAGE):
    viewer = require_login()
    c = _conversation_for(viewer, conversation)
    filters = {"conversation": c.name, "is_deleted": 0}
    if before:
        filters["sent_on"] = ("<", get_datetime(before))
    rows = frappe.get_all("Social Message", filters=filters,
                          fields=["name", "sender", "content", "sent_on"],
                          order_by="sent_on desc", page_length=min(cint(limit) or PAGE, 200))
    rows.reverse()
    p = _profiles([c.other]).get(c.other)
    _mark_read(c)
    return {
        "conversation": c.name,
        "other": {"display_name": p.display_name if p else c.other,
                  "profile_slug": p.profile_slug if p else None,
                  "profile_image": p.profile_image if p else None},
        "can_reply": can_message(viewer, c.other) or bool(rows),  # existing threads stay open unless blocked
        "blocked": is_blocked(viewer, c.other),
        "messages": [{"name": r.name, "mine": r.sender == viewer, "content": r.content,
                      "sent_on": str(r.sent_on)} for r in rows],
    }


@frappe.whitelist()
def send_message(conversation, content):
    viewer = require_login()
    _guard_enabled()
    c = _conversation_for(viewer, conversation)
    content = (content or "").strip()
    if not content:
        frappe.throw(frappe._("Message is empty."))
    if len(content) > 4000:
        frappe.throw(frappe._("Message is too long."))
    if is_blocked(viewer, c.other):
        frappe.throw(frappe._("You can't message this member."), frappe.PermissionError)
    has_history = frappe.db.exists("Social Message", {"conversation": c.name})
    if not has_history and not can_message(viewer, c.other):
        frappe.throw(frappe._("This member isn't accepting messages from you."), frappe.PermissionError)
    enforce_rate_limit("message", 20)
    check_content(content)
    now = now_datetime()
    msg = frappe.get_doc({"doctype": "Social Message", "conversation": c.name, "sender": viewer,
                          "content": content, "sent_on": now}).insert(ignore_permissions=True)
    frappe.db.set_value("Social Conversation", c.name,
                        {"last_message": content[:280], "last_sender": viewer, "last_message_at": now,
                         c.me_field: now}, update_modified=False)
    frappe.db.commit()
    payload = {"conversation": c.name, "name": msg.name, "content": content, "sent_on": str(now)}
    frappe.publish_realtime("es_social_message", payload, user=c.other, after_commit=True)
    return dict(payload, mine=True)


def _mark_read(c):
    frappe.db.set_value("Social Conversation", c.name, c.me_field, now_datetime(), update_modified=False)
    frappe.db.commit()


@frappe.whitelist()
def mark_read(conversation):
    viewer = require_login()
    _mark_read(_conversation_for(viewer, conversation))
    return {"ok": True}


@frappe.whitelist()
def delete_message(name):
    viewer = require_login()
    sender = frappe.db.get_value("Social Message", name, "sender")
    if sender != viewer:
        frappe.throw(frappe._("You can only delete your own messages."), frappe.PermissionError)
    frappe.db.set_value("Social Message", name, "is_deleted", 1)
    frappe.db.commit()
    return {"ok": True}


def unread_for(user):
    return frappe.db.sql(
        """select count(*) from `tabSocial Conversation`
           where last_message_at is not null and last_sender != %(u)s and (
             (user_a=%(u)s and (a_last_read is null or a_last_read < last_message_at)) or
             (user_b=%(u)s and (b_last_read is null or b_last_read < last_message_at)))""",
        {"u": user})[0][0]


@frappe.whitelist(allow_guest=True)
def unread_count():
    viewer = get_viewer()
    if viewer == GUEST or not cint(get_settings().get("enable_messaging")):
        return 0
    return unread_for(viewer)


@frappe.whitelist()
def set_message_privacy(allow_messages_from):
    viewer = require_login()
    if allow_messages_from not in ("Connections", "Everyone", "No one"):
        frappe.throw(frappe._("Unknown option."))
    prof = frappe.db.get_value("Social Profile", {"user": viewer}, "name")
    if prof:
        frappe.db.set_value("Social Profile", prof, "allow_messages_from", allow_messages_from)
        frappe.db.commit()
    return {"ok": True}
