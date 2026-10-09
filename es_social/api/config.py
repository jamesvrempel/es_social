# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Lightweight client configuration for the portal."""

import frappe

from es_social.social.utils import client_flags, get_settings, get_viewer, is_guest, signup_url


@frappe.whitelist(allow_guest=True)
def get_client_config():
    viewer = get_viewer()
    s = get_settings()
    return {
        "is_guest": is_guest(viewer),
        "signup_url": signup_url(),
        "max_upload_mb": s.max_upload_size_mb or 5,
        "enable_groups": bool(s.enable_groups),
        "enable_messaging": bool(s.enable_messaging),
        "default_visibility": s.default_visibility or "Public",
        "flags": client_flags(viewer),
    }
