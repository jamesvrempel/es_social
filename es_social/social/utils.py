# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Shared helpers for the ES Social module.

This is ordinary app code (not a Server Script), so the RestrictedPython sandbox
does not apply: imports, str methods, f-strings and helper defs are all fine.
"""

import re

import frappe
from frappe.utils import cint, now_datetime

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

    full_name, user_image = frappe.db.get_value(
        "User", user, ["full_name", "user_image"]) or (None, None)
    full_name = full_name or user.split("@")[0]
    doc = frappe.new_doc("Social Profile")
    doc.user = user
    doc.display_name = full_name
    # seed the avatar from the sign-in provider (Google etc. set User.user_image);
    # Microsoft Graph photo URLs need an access token, so they're skipped
    if user_image and "graph.microsoft.com" not in user_image:
        doc.profile_image = user_image
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

    sql = "(" + " or ".join(clauses) + ")"

    # posts awaiting group-admin / moderator approval are visible to their
    # author only (admins review them through the moderation endpoints)
    sql += (f" and (coalesce({alias}.approval_status, 'Approved') = 'Approved'"
            f" or {alias}.author = {esc(user)})")

    # blocking hides content in both directions
    from es_social.social.moderation import get_block_ids
    blocked = get_block_ids(user)
    if blocked:
        b_list = ", ".join(esc(b) for b in blocked)
        sql += f" and {alias}.author not in ({b_list})"
    return sql


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


def check_content(text, allow_hold=False):
    """Blocked-keyword filter.

    Returns True when the content should be *held for review* (only when the
    caller supports it and ES Social Settings → Blocked Keyword Action is
    "Hold for review"); otherwise raises on a match. Returns False when clean.
    """
    if not text:
        return False
    settings = get_settings()
    if not settings.enable_profanity_filter or not settings.blocked_keywords:
        return False
    lowered = frappe.utils.strip_html(text or "").lower()
    for kw in settings.blocked_keywords.split(","):
        kw = kw.strip().lower()
        if kw and kw in lowered:
            if allow_hold and settings.get("keyword_action") == "Hold for review":
                return True
            frappe.throw(frappe._("Your content contains language that isn't allowed here."))
    return False


# --------------------------------------------------------------------------- #
# Counters (atomic)
# --------------------------------------------------------------------------- #

def bump(doctype, name, field, delta):
    """Atomic counter update — safe under concurrency."""
    frappe.db.sql(
        f"update `tab{doctype}` set `{field}` = greatest(0, coalesce(`{field}`,0) + %s) where name = %s",
        (delta, name),
    )


# --------------------------------------------------------------------------- #
# Guest browsing
# --------------------------------------------------------------------------- #
# Reading the social area no longer requires an account. Anything that writes
# (posting, commenting, reacting, sharing, joining, connecting, uploading) still
# goes through require_login(). Read endpoints use get_viewer() instead, which
# returns "Guest" for anonymous visitors while guest browsing is enabled.

GUEST = "Guest"

# Fields that carry a member's email address (User IDs and Social Profile names
# are emails). They are stripped from every payload sent to anonymous visitors.
GUEST_HIDDEN_FIELDS = ("author", "author_profile", "user", "owner_user",
                       "created_by", "from_user", "to_user")


def is_guest(user=None):
    return (user or frappe.session.user) == GUEST


def guest_browsing_enabled():
    """ES Social Settings → Allow Guest Browsing (treated as on until saved)."""
    try:
        value = get_settings().get("allow_guest_browsing")
    except Exception:
        return True
    return True if value is None else bool(cint(value))


def get_viewer():
    """Current user for read-only endpoints. Guests are allowed while guest
    browsing is enabled; otherwise behaves exactly like require_login()."""
    user = frappe.session.user
    if user == GUEST and not guest_browsing_enabled():
        require_login()
    return user


def scrub_for_guest(row, viewer):
    """Remove email-bearing fields from a dict when the viewer is a guest."""
    if viewer != GUEST or not row:
        return row
    for f in GUEST_HIDDEN_FIELDS:
        if f in row:
            row.pop(f, None)
    return row


def signup_url():
    try:
        url = get_settings().get("signup_url")
    except Exception:
        url = None
    return url or "/login#signup"


def guard_page(redirect_to, guest_ok=True):
    """Page controller helper: redirect guests to login only when the page is
    member-only (guest_ok=False) or guest browsing has been switched off."""
    if frappe.session.user != GUEST:
        return
    if guest_ok and guest_browsing_enabled():
        return
    frappe.local.flags.redirect_location = f"/login?redirect-to={redirect_to}"
    raise frappe.Redirect


def apply_guest_context(context):
    """Common page context: guest flag, sign-up URL and social sign-in buttons."""
    context.is_guest = frappe.session.user == GUEST
    context.signup_url = signup_url()
    context.es_brand = brand_name()
    # cache-busting: asset URLs carry the app version, so every release gets
    # URLs Cloudflare / browsers have never cached
    from es_social import __version__
    context.es_v = __version__
    context.login_providers = []
    context.es_flags = client_flags(frappe.session.user)
    if context.is_guest:
        try:
            from es_social.social.signup import get_login_providers
            context.login_providers = get_login_providers()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "es_social: login providers failed")
    return context


def brand_name():
    """Name shown in place of "ES Social" (ES Social Settings → Branding)."""
    if getattr(frappe.local, "es_brand", None):
        return frappe.local.es_brand
    s = get_settings()
    source = s.get("brand_source") or "Website name"
    name = None
    if source == "Custom":
        name = (s.get("brand_name") or "").strip()
    elif source == "Website name":
        name = (frappe.db.get_single_value("Website Settings", "app_name") or "").strip()
    if not name:
        name = _domain_name()
    frappe.local.es_brand = name or "ES Social"
    return frappe.local.es_brand


def _domain_name():
    """The host the visitor is on (handles sites with several domains),
    else the site name. A leading "www." is dropped."""
    host = None
    try:
        req = getattr(frappe.local, "request", None)
        host = req.host.split(":")[0] if req and req.host else None
    except Exception:
        host = None
    host = host or getattr(frappe.local, "site", "") or ""
    return host[4:] if host.lower().startswith("www.") else host


def client_flags(user=None):
    """Feature switches the portal UI needs (also sent to JS as ES_CFG.flags)."""
    user = user or frappe.session.user
    s = get_settings()
    flags = {
        "messaging": bool(cint(s.get("enable_messaging"))),
        "pages": bool(cint(s.get("enable_pages"))),
        "events": s.get("enable_events") is None or bool(cint(s.get("enable_events"))),
        "groups": bool(cint(s.get("enable_groups"))),
        "moderator": False,
    }
    if user != GUEST:
        from es_social.social.moderation import is_privileged
        flags["moderator"] = is_privileged(user) or bool(frappe.db.exists(
            "Social Group Member", {"user": user, "status": "Active", "role": ("in", ["Admin", "Moderator"])}))
    return flags


def require_login():
    """Gate for every write action: must be logged in and not suspended."""
    if frappe.session.user == GUEST:
        frappe.throw(frappe._("Please log in or sign up to do that."), frappe.PermissionError)
    from es_social.social.moderation import assert_not_suspended
    assert_not_suspended(frappe.session.user)
    return frappe.session.user
