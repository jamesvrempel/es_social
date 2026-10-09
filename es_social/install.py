# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Post-install setup: roles + default settings."""

import frappe

ROLES = [
    ("Social User", "Standard member of the social network."),
    ("Social Moderator", "Reviews reports and moderates content."),
    ("Social Admin", "Manages ES Social settings, groups and pages."),
]


def after_install():
    _ensure_roles()
    _ensure_settings()
    frappe.db.commit()


def after_migrate():
    try:
        ensure_member_role_is_website_only()
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "es_social: Social User role fix failed")
    try:
        ensure_moderation_dashboard()
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "es_social: moderation dashboard setup failed")


def ensure_member_role_is_website_only():
    """Members must be Website Users. Frappe makes anyone holding a role with
    Desk Access a System User, and it auto-creates "Social User" (with Desk
    Access ON) while syncing DocTypes, before after_install runs, so the role
    is switched off here on every migrate."""
    if frappe.db.exists("Role", "Social User") and \
            frappe.db.get_value("Role", "Social User", "desk_access"):
        frappe.db.set_value("Role", "Social User", "desk_access", 0)
        frappe.clear_cache()


CARDS = [
    ("ES Social: Open Reports", "Social Report", [["Social Report", "status", "=", "Open"]]),
    ("ES Social: Pending Posts", "Social Post",
     [["Social Post", "approval_status", "=", "Pending"], ["Social Post", "is_deleted", "=", 0]]),
    ("ES Social: Suspended Members", "Social Profile", [["Social Profile", "suspended", "=", 1]]),
    ("ES Social: New Members (30d)", "Social Profile", [["Social Profile", "creation", "Timespan", "last month"]]),
]
CHARTS = [
    ("ES Social: Reports per Day", "Social Report"),
    ("ES Social: Moderation Actions", "Social Moderation Log"),
    ("ES Social: Posts per Day", "Social Post"),
]
DASHBOARD = "ES Social Moderation"


def ensure_moderation_dashboard():
    """Desk dashboard (/app/dashboard-view/ES Social Moderation): number cards
    + daily charts. Created once; edits made in Desk are kept."""
    import json
    for label, dt, filters in CARDS:
        if not frappe.db.exists("Number Card", label):
            frappe.get_doc({"doctype": "Number Card", "label": label, "type": "Document Type",
                            "document_type": dt, "function": "Count", "is_public": 1,
                            "module": "ES Social", "show_percentage_stats": 1, "stats_time_interval": "Weekly",
                            "filters_json": json.dumps(filters)}).insert(ignore_permissions=True)
    for name, dt in CHARTS:
        if not frappe.db.exists("Dashboard Chart", name):
            frappe.get_doc({"doctype": "Dashboard Chart", "chart_name": name, "chart_type": "Count",
                            "document_type": dt, "based_on": "creation", "timeseries": 1,
                            "timespan": "Last Month", "time_interval": "Daily", "type": "Line",
                            "is_public": 1, "module": "ES Social", "filters_json": "[]"
                            }).insert(ignore_permissions=True)
    if not frappe.db.exists("Dashboard", DASHBOARD):
        frappe.get_doc({"doctype": "Dashboard", "dashboard_name": DASHBOARD, "module": "ES Social",
                        "cards": [{"card": c[0]} for c in CARDS],
                        "charts": [{"chart": c[0], "width": "Full"} for c in CHARTS]}
                       ).insert(ignore_permissions=True)


def _ensure_roles():
    ensure_member_role_is_website_only()
    for name, desc in ROLES:
        if not frappe.db.exists("Role", name):
            frappe.get_doc({
                "doctype": "Role",
                "role_name": name,
                "desk_access": 0 if name == "Social User" else 1,
                "restrict_to_domain": None,
            }).insert(ignore_permissions=True)


def _ensure_settings():
    settings = frappe.get_single("ES Social Settings")
    if not settings.default_visibility:
        settings.default_visibility = "Public"
    if not settings.posts_per_minute:
        settings.posts_per_minute = 5
    if not settings.comments_per_minute:
        settings.comments_per_minute = 20
    if settings.allow_public_signup is None:
        settings.allow_public_signup = 1
    settings.flags.ignore_permissions = True
    settings.save(ignore_permissions=True)


def backfill_profiles():
    """Utility: `bench execute es_social.install.backfill_profiles` to create
    Social Profiles + grant the Social User role to all existing website users."""
    from es_social.social.utils import get_or_create_profile
    users = frappe.get_all("User",
                           filters={"enabled": 1, "user_type": "Website User"},
                           pluck="name")
    made = 0
    for u in users:
        if u in ("Guest", "Administrator"):
            continue
        user = frappe.get_doc("User", u)
        if "Social User" not in [r.role for r in user.roles]:
            user.add_roles("Social User")
        get_or_create_profile(u)
        made += 1
    frappe.db.commit()
    print(f"Backfilled {made} profiles.")
