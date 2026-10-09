# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Member notification & privacy preferences (/social/settings)."""

import frappe
from frappe.utils import cint

from es_social.social.digest import CATEGORY_FIELDS, get_prefs
from es_social.social.utils import require_login

def _brand():
    from es_social.social.utils import brand_name
    return brand_name()


FIELDS = ["digest_frequency"] + list(CATEGORY_FIELDS.values()) + ["email_messages"]


@frappe.whitelist()
def get_settings():
    viewer = require_login()
    p = get_prefs(viewer)
    frappe.db.commit()
    out = {f: p.get(f) for f in FIELDS}
    out["allow_messages_from"] = frappe.db.get_value("Social Profile", {"user": viewer},
                                                     "allow_messages_from") or "Connections"
    return out


@frappe.whitelist()
def save_settings(**kwargs):
    viewer = require_login()
    p = get_prefs(viewer)
    if kwargs.get("digest_frequency") in ("Daily", "Weekly", "Off"):
        p.digest_frequency = kwargs["digest_frequency"]
    for f in FIELDS[1:]:
        if f in kwargs:
            p.set(f, 1 if cint(kwargs[f]) else 0)
    p.save(ignore_permissions=True)
    amf = kwargs.get("allow_messages_from")
    if amf in ("Connections", "Everyone", "No one"):
        prof = frappe.db.get_value("Social Profile", {"user": viewer}, "name")
        if prof:
            frappe.db.set_value("Social Profile", prof, "allow_messages_from", amf)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def unsubscribe(token):
    """One-click unsubscribe from digest emails (no login needed)."""
    name = frappe.db.get_value("Social Notification Settings", {"unsubscribe_token": token}, "name") if token else None
    if name:
        frappe.db.set_value("Social Notification Settings", name, "digest_frequency", "Off")
        frappe.db.commit()
        frappe.respond_as_web_page(frappe._("Unsubscribed"),
                                   frappe._("You won't receive {0} digest emails any more. "
                                            "You can turn them back on in your settings.").format(_brand()),
                                   indicator_color="green")
    else:
        frappe.respond_as_web_page(frappe._("Link not recognised"),
                                   frappe._("This unsubscribe link is invalid or has expired."),
                                   indicator_color="orange")
