# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""v0.9 (roadmap phases 2-5): backfill new fields, migrate legacy blocks,
add feed indexes, seed new settings."""

import frappe
from frappe.utils import now_datetime

SETTING_DEFAULTS = {
    "enable_events": 1, "keyword_action": "Reject", "auto_hide_report_threshold": 3,
    "enable_fanout": 0, "fanout_celebrity_threshold": 500, "feed_inbox_cap": 500,
    "log_slow_feeds_ms": 800, "guest_cache_seconds": 45, "trending_min_account_days": 3,
    "enable_digests": 1, "digest_hour": 7, "messaging_provider": "Built-in",
}

INDEXES = [
    ("Social Post", ["author", "posted_on"]),
    ("Social Post", ["group", "posted_on"]),
    ("Social Post", ["visibility", "posted_on"]),
    ("Social Post", ["page", "posted_on"]),
    ("Social Post", ["score"]),
    ("Social Comment", ["reference_post", "posted_on"]),
    ("Social Reaction", ["reference_doctype", "reference_name", "user"]),
    ("Social Feed Item", ["user", "created_on"]),
    ("Social Message", ["conversation", "sent_on"]),
    ("Social Event RSVP", ["event", "user"]),
    ("Social Affinity", ["user", "other_user"]),
    ("Social Block", ["blocker", "blocked"]),
]


def _unset(field):
    return not frappe.db.sql("select 1 from `tabSingles` where doctype=%s and field=%s",
                             ("ES Social Settings", field))


def execute():
    frappe.reload_doc("es_social", "doctype", "es_social_settings")
    for field, value in SETTING_DEFAULTS.items():
        if _unset(field):
            frappe.db.set_single_value("ES Social Settings", field, value)
    frappe.clear_document_cache("ES Social Settings", "ES Social Settings")

    # existing posts are approved
    frappe.db.sql("""update `tabSocial Post` set approval_status='Approved'
                     where approval_status is null or approval_status=''""")
    # profiles default to friends-only messaging
    frappe.db.sql("""update `tabSocial Profile` set allow_messages_from='Connections'
                     where allow_messages_from is null or allow_messages_from=''""")

    # legacy blocks (Social Connection status=Blocked) -> Social Block
    for c in frappe.get_all("Social Connection", filters={"status": "Blocked"},
                            fields=["name", "from_user", "to_user"]):
        if c.from_user and c.to_user and not frappe.db.exists(
                "Social Block", {"blocker": c.from_user, "blocked": c.to_user}):
            frappe.get_doc({"doctype": "Social Block", "blocker": c.from_user, "blocked": c.to_user,
                            "blocked_on": now_datetime()}).insert(ignore_permissions=True)
        frappe.delete_doc("Social Connection", c.name, ignore_permissions=True, force=True)

    for doctype, fields in INDEXES:
        try:
            frappe.db.add_index(doctype, fields, index_name="es_" + "_".join(fields)[:50])
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"es_social: index on {doctype} {fields} failed")
    frappe.db.commit()
