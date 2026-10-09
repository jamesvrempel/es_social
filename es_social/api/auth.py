# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Social sign-in entry point for the ES Social portal."""

from urllib.parse import urlparse

import frappe

from es_social.social.signup import get_login_providers, is_enabled_provider


def _safe_redirect(redirect_to):
    """Only allow same-site relative paths (blocks open redirects)."""
    redirect_to = (redirect_to or "").strip()
    if not redirect_to.startswith("/") or redirect_to.startswith("//") or "\\" in redirect_to:
        return "/social"
    parsed = urlparse(redirect_to)
    if parsed.scheme or parsed.netloc:
        return "/social"
    return redirect_to


@frappe.whitelist(allow_guest=True, methods=["GET"])
def social_login(provider, redirect_to="/social"):
    """Start the OAuth flow for *provider* and come back to *redirect_to*.

    The authorize URL (with its single-use state token) is minted here, on
    click, rather than on every page render.
    """
    redirect_to = _safe_redirect(redirect_to)
    if frappe.session.user != "Guest":
        location = redirect_to
    elif not is_enabled_provider(provider):
        location = "/login?redirect-to=" + redirect_to
    else:
        from frappe.utils.oauth import get_oauth2_authorize_url
        location = get_oauth2_authorize_url(provider, redirect_to)
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = location


@frappe.whitelist(allow_guest=True)
def providers():
    """Enabled sign-in providers (display data only)."""
    return get_login_providers()
