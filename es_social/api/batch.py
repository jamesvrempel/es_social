# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Batch reads: several read-only calls in one HTTP round trip.

    POST /api/method/es_social.api.batch.get
    requests = [{"method": "profile.get_profile", "args": {"slug": "james"}},
                {"method": "albums.list_albums", "args": {"slug": "james"}}]

Only the read methods in ALLOWED can be batched (write methods never), each
runs with the caller's own permissions, and one failing call doesn't fail the
others. Max 10 calls per batch.
"""

import json

import frappe

ALLOWED = {
    "feed.get_feed", "feed.get_profile_feed", "feed.get_group_feed", "feed.get_trending",
    "profile.get_profile", "profile.search_people",
    "albums.list_albums", "albums.get_album", "albums.list_group_albums",
    "photos.get_photos",
    "groups.get_group", "groups.list_my_groups", "groups.discover_groups",
    "group_admin.list_members",
    "connections.connection_status", "connections.pending_requests", "connections.list_connections",
    "comments.list_comments",
    "events.upcoming",
    "pages.get_page", "pages.get_page_feed", "pages.list_pages", "pages.my_pages",
    "messages.unread_count", "messages.list_conversations",
    "config.get_client_config",
}
MAX_CALLS = 10


@frappe.whitelist(allow_guest=True)
def get(requests):
    if isinstance(requests, str):
        requests = json.loads(requests or "[]")
    if not isinstance(requests, list) or len(requests) > MAX_CALLS:
        frappe.throw(frappe._("Send between 1 and {0} requests.").format(MAX_CALLS))
    out = []
    for req in requests:
        method = (req or {}).get("method")
        args = (req or {}).get("args") or {}
        if method not in ALLOWED or not isinstance(args, dict):
            out.append({"method": method, "error": "not allowed"})
            continue
        try:
            fn = frappe.get_attr(f"es_social.api.{method}")
            out.append({"method": method, "data": fn(**args)})
        except frappe.PermissionError:
            frappe.clear_messages()
            out.append({"method": method, "error": "forbidden"})
        except Exception as e:
            frappe.clear_messages()
            out.append({"method": method, "error": str(e)[:200] or e.__class__.__name__})
    return out
