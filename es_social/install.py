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


def _ensure_roles():
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
