# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Lightweight client configuration for the portal."""

import frappe

from es_social.social.utils import get_settings, require_login


@frappe.whitelist()
def get_client_config():
    require_login()
    s = get_settings()
    return {
        "max_upload_mb": s.max_upload_size_mb or 5,
        "enable_groups": bool(s.enable_groups),
        "enable_messaging": bool(s.enable_messaging),
        "default_visibility": s.default_visibility or "Public",
    }
