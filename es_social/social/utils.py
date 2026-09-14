# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Shared helpers for the ES Social module.

This is ordinary app code (not a Server Script), so the RestrictedPython sandbox
does not apply: imports, str methods, f-strings and helper defs are all fine.
"""

import re

import frappe
from frappe.utils import now_datetime

CONN_CACHE_TTL = 300  # seconds
REACTION_TYPES = ["Like", "Love", "Care", "Haha", "Wow", "Sad", "Angry"]


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

def get_settings():
    return frappe.get_cached_doc("ES Social Settings")


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #

def slugify(value):
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or frappe.generate_hash(length=8)


def unique_slug(base, doctype, field="profile_slug", exclude=None):
    """Return a slug unique within *doctype*.*field*."""
    base = slugify(base)
    slug = base
    i = 1
    while True:
        filters = {field: slug}
        existing = frappe.db.get_value(doctype, filters, "name")
        if not existing or existing == exclude:
            return slug
        i += 1
        slug = f"{base}-{i}"


def get_or_create_profile(user=None):
    """Fetch the Social Profile for *user*, creating it if missing."""
    user = user or frappe.session.user
    if user in ("Guest", "Administrator"):
        # never auto-create for these system accounts
        name = frappe.db.get_value("Social Profile", {"user": user}, "name")
        return frappe.get_doc("Social Profile", name) if name else None

    name = frappe.db.get_value("Social Profile", {"user": user}, "name")
    if name:
        return frappe.get_doc("Social Profile", name)

    full_name = frappe.db.get_value("User", user, "full_name") or user.split("@")[0]
    doc = frappe.new_doc("Social Profile")
    doc.user = user
    doc.display_name = full_name
    doc.profile_slug = unique_slug(full_name, "Social Profile")
    doc.insert(ignore_permissions=True)
    return doc


def create_profile_for_user(doc, method=None):
    """User.after_insert hook: provision a social identity for new website users."""
    try:
        settings = get_settings()
    except Exception:
        settings = None

    if settings and not settings.allow_public_signup:
        return
    if doc.name in ("Guest", "Administrator"):
        return

    # grant the member role
    if "Social User" not in [r.role for r in (doc.get("roles") or [])]:
        try:
            doc.add_roles("Social User")
        except Exception:
            frappe.log_error(frappe.get_traceback(), "es_social: add Social User role failed")

    try:
        get_or_create_profile(doc.name)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "es_social: profile creation failed")


# --------------------------------------------------------------------------- #
# Connections (cached)
# --------------------------------------------------------------------------- #

def _conn_cache_key(user):
    return f"es_social:connections:{user}"


def get_connection_ids(user=None):
    """Return a set of user IDs that *user* is accepted-connected to (cached)."""
    user = user or frappe.session.user
    key = _conn_cache_key(user)
    cached = frappe.cache().get_value(key)
    if cached is not None:
        return set(cached)

    rows = frappe.db.sql(
        """
        select from_user, to_user from `tabSocial Connection`
        where status = 'Accepted' and (from_user = %(u)s or to_user = %(u)s)
        """,
        {"u": user},
        as_dict=True,
    )
    ids = set()
    for r in rows:
        ids.add(r.to_user if r.from_user == user else r.from_user)
    frappe.cache().set_value(key, list(ids), expires_in_sec=CONN_CACHE_TTL)
    return ids


def clear_connection_cache(*users):
    for u in users:
        if u:
            frappe.cache().delete_value(_conn_cache_key(u))


def are_connected(a, b):
    return b in get_connection_ids(a)


def pair_key(a, b):
    return "::".join(sorted([a or "", b or ""]))


# --------------------------------------------------------------------------- #
# Groups
# --------------------------------------------------------------------------- #

def get_group_ids(user=None):
    """Groups where *user* is an active member."""
    user = user or frappe.session.user
    rows = frappe.get_all(
        "Social Group Member",
        filters={"user": user, "status": "Active"},
        pluck="group",
    )
    return set(rows)


def get_member_role(group, user=None):
    user = user or frappe.session.user
    return frappe.db.get_value(
        "Social Group Member", {"group": group, "user": user, "status": "Active"}, "role"
    )


# --------------------------------------------------------------------------- #
# Visibility SQL (used by permission_query_conditions)
# --------------------------------------------------------------------------- #

def build_post_visibility_sql(user, alias="`tabSocial Post`"):
    """Boolean SQL expression: which posts may *user* see.

    Uses frappe.db.escape throughout — never string-formats raw user input.
    """
    esc = frappe.db.escape
    clauses = [
        f"{alias}.author = {esc(user)}",
        f"{alias}.visibility = 'Public'",
    ]

    conns = get_connection_ids(user)
    if conns:
        in_list = ", ".join(esc(c) for c in conns)
        clauses.append(
            f"({alias}.visibility = 'Connections' and {alias}.author in ({in_list}))"
        )

    groups = get_group_ids(user)
    if groups:
        g_list = ", ".join(esc(g) for g in groups)
        clauses.append(f"({alias}.visibility = 'Group' and {alias}.group in ({g_list}))")

    return "(" + " or ".join(clauses) + ")"


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #

def notify(user, subject, message="", reference_doctype=None, reference_name=None,
           link=None):
    """Create a Notification Log row and push it over realtime. Best-effort."""
    if not user or user == frappe.session.user or user in ("Guest", "Administrator"):
        return
    try:
        log = frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": user,
            "type": "Alert",
            "subject": subject,
            "email_content": message,
            "document_type": reference_doctype,
            "document_name": reference_name,
        })
        log.insert(ignore_permissions=True)
        frappe.publish_realtime(
            "es_social_notification",
            {"subject": subject, "link": link, "reference_name": reference_name},
            user=user,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "es_social: notify failed")


# --------------------------------------------------------------------------- #
# Rate limiting & content filtering
# --------------------------------------------------------------------------- #

def enforce_rate_limit(action, per_minute):
    """Raise if *user* exceeded *per_minute* of *action* in the last 60s."""
    if not per_minute:
        return
    user = frappe.session.user
    key = f"es_social:rl:{action}:{user}"
    cache = frappe.cache()
    count = cache.get_value(key) or 0
    if int(count) >= int(per_minute):
        frappe.throw(
            frappe._("You're doing that too quickly. Please wait a moment and try again."),
            frappe.RateLimitExceededError if hasattr(frappe, "RateLimitExceededError") else frappe.ValidationError,
        )
    cache.set_value(key, int(count) + 1, expires_in_sec=60)


def check_content(text):
    """Reject content containing blocked keywords when the filter is on."""
    if not text:
        return
    settings = get_settings()
    if not settings.enable_profanity_filter or not settings.blocked_keywords:
        return
    lowered = frappe.utils.strip_html(text or "").lower()
    for kw in settings.blocked_keywords.split(","):
        kw = kw.strip().lower()
        if kw and kw in lowered:
            frappe.throw(frappe._("Your content contains language that isn't allowed here."))


# --------------------------------------------------------------------------- #
# Counters (atomic)
# --------------------------------------------------------------------------- #

def bump(doctype, name, field, delta):
    """Atomic counter update — safe under concurrency."""
    frappe.db.sql(
        f"update `tab{doctype}` set `{field}` = greatest(0, coalesce(`{field}`,0) + %s) where name = %s",
        (delta, name),
    )


def require_login():
    if frappe.session.user == "Guest":
        frappe.throw(frappe._("Please log in to continue."), frappe.PermissionError)
    return frappe.session.user
