# Copyright (c) 2026, Enterprise Systems Australia and contributors
import frappe


def _placeholder_profile(user):
    """Minimal stand-in for users with no Social Profile row.

    get_or_create_profile() intentionally never auto-creates a profile for
    Administrator or Guest, so the sidebar still needs something to render.
    Mirrors the shape of SocialProfile.get_public_dict().
    """
    full_name, user_image = frappe.db.get_value(
        "User", user, ["full_name", "user_image"]) or (None, None)
    return {
        "user": user,
        "display_name": full_name or user,
        "profile_slug": None,
        "headline": None,
        "profile_image": user_image,
        "cover_image": None,
        "bio": None,
        "location": None,
        "website": None,
        "connection_count": 0,
        "post_count": 0,
    }


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/social"
        raise frappe.Redirect

    from es_social.social.utils import get_or_create_profile
    prof = get_or_create_profile(frappe.session.user)
    context.me = (prof.get_public_dict() if prof
                  else _placeholder_profile(frappe.session.user))
    context.no_cache = 1
    context.show_sidebar = False
    return context
