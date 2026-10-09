# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Email digests: one summary email instead of an email per notification.

Runs hourly; acts once a day at ES Social Settings → Send Digests At (site
time). Daily subscribers get yesterday's unread activity, weekly subscribers
get the week's on Mondays. Members choose frequency and categories on
/social/settings; every email carries a one-click unsubscribe link (Spam Act
2003). Digests are kept separate from any ERPNext sales email.
"""

import frappe
from frappe.utils import add_days, cint, get_datetime, getdate, now_datetime

CATEGORY_FIELDS = {
    "reactions": "email_reactions",
    "comments": "email_comments",
    "friend_requests": "email_friend_requests",
    "groups": "email_groups",
    "events": "email_events",
}
CATEGORY_LABELS = {
    "reactions": "Reactions", "comments": "Comments & replies", "friend_requests": "Friend requests",
    "groups": "Groups", "events": "Events", "other": "Account",
}
SOCIAL_DOCTYPES = ("Social Post", "Social Connection", "Social Group", "Social Event", "Social Comment")


def categorize(doc_type, subject):
    subj = (subject or "").lower()
    if doc_type == "Social Event":
        return "events"
    if doc_type == "Social Connection":
        return "friend_requests"
    if doc_type == "Social Group" or "awaiting approval" in subj:
        return "groups"
    if doc_type in ("Social Post", "Social Comment"):
        return "reactions" if "reacted" in subj else "comments"
    return "other"


def get_prefs(user, create=True):
    name = frappe.db.get_value("Social Notification Settings", {"user": user}, "name")
    if name:
        return frappe.get_doc("Social Notification Settings", name)
    if not create:
        return None
    doc = frappe.get_doc({"doctype": "Social Notification Settings", "user": user,
                          "unsubscribe_token": frappe.generate_hash(length=32)})
    doc.insert(ignore_permissions=True)
    return doc


def send_digests(force=False):
    from es_social.social.utils import get_settings
    s = get_settings()
    if s.get("enable_digests") is not None and not cint(s.get("enable_digests")):
        return
    now = now_datetime()
    if not force and now.hour != cint(s.get("digest_hour") if s.get("digest_hour") is not None else 7):
        return
    weekly_today = getdate(now).weekday() == 0  # Monday

    users = frappe.db.sql(
        """select distinct n.for_user from `tabNotification Log` n
           join `tabUser` u on u.name = n.for_user and u.enabled = 1
           where n.`read` = 0 and n.creation >= %s and n.document_type in %s""",
        (add_days(now, -7), SOCIAL_DOCTYPES), pluck=True)
    if cint(s.get("enable_messaging")):
        users = set(users) | set(frappe.db.sql(
            """select user_a from `tabSocial Conversation` where last_message_at >= %(d)s and last_sender != user_a
               and (a_last_read is null or a_last_read < last_message_at)
               union select user_b from `tabSocial Conversation` where last_message_at >= %(d)s
               and last_sender != user_b and (b_last_read is null or b_last_read < last_message_at)""",
            {"d": add_days(now, -7)}, pluck=True))
    sent = 0
    for user in users:
        try:
            if _send_one(user, now, weekly_today, messaging=cint(s.get("enable_messaging"))):
                sent += 1
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"es_social: digest failed for {user}")
    frappe.db.commit()
    return sent


def _send_one(user, now, weekly_today, messaging=False):
    prefs = get_prefs(user)
    freq = prefs.digest_frequency or "Daily"
    if freq == "Off" or (freq == "Weekly" and not weekly_today):
        return False
    window = 7 if freq == "Weekly" else 1
    since = get_datetime(prefs.last_digest_on) if prefs.last_digest_on else add_days(now, -window)
    since = max(since, add_days(now, -window))
    if prefs.last_digest_on and getdate(prefs.last_digest_on) == getdate(now):
        return False  # already sent today

    rows = frappe.get_all("Notification Log",
                          filters={"for_user": user, "read": 0, "creation": (">=", since),
                                   "document_type": ("in", SOCIAL_DOCTYPES)},
                          fields=["subject", "document_type", "creation"], order_by="creation desc",
                          page_length=200)
    buckets = {}
    for r in rows:
        cat = categorize(r.document_type, r.subject)
        field = CATEGORY_FIELDS.get(cat)
        if field and not cint(prefs.get(field)):
            continue
        buckets.setdefault(cat, []).append(frappe.utils.strip_html(r.subject or ""))
    unread_msgs = 0
    if messaging and cint(prefs.email_messages):
        from es_social.api.messages import unread_for
        unread_msgs = unread_for(user)
    if not buckets and not unread_msgs:
        return False

    site = frappe.utils.get_url()
    unsub = f"{site}/api/method/es_social.api.notification_prefs.unsubscribe?token={prefs.unsubscribe_token}"
    total = sum(len(v) for v in buckets.values()) + (1 if unread_msgs else 0)
    from es_social.social.utils import brand_name
    html = frappe.render_template("templates/emails/social_digest.html", {
        "name": frappe.db.get_value("User", user, "first_name") or "there",
        "buckets": [(CATEGORY_LABELS.get(k, k.title()), v[:8], max(len(v) - 8, 0)) for k, v in buckets.items()],
        "unread_messages": unread_msgs, "site": site, "unsubscribe_url": unsub,
        "settings_url": f"{site}/social/settings", "weekly": freq == "Weekly",
        "brand": brand_name(),
    })
    from es_social.social.utils import brand_name
    brand = brand_name()
    subject = frappe._("Your {0} {1}: {2} new").format(
        brand, frappe._("weekly summary") if freq == "Weekly" else frappe._("daily summary"), total)
    frappe.sendmail(recipients=[user], subject=subject, message=html, delayed=True,
                    reference_doctype="Social Notification Settings", reference_name=prefs.name,
                    add_unsubscribe_link=0, header=None)
    frappe.db.set_value("Social Notification Settings", prefs.name, "last_digest_on", now, update_modified=False)
    return True
