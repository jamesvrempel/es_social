# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Social sign-up (Google, Microsoft, GitHub, ... via Frappe Social Login Keys)
and ES ERP customer provisioning.

Flow for a brand-new visitor who clicks "Continue with Google":

    /api/method/es_social.api.auth.social_login?provider=google&redirect_to=/social
      -> provider consent screen
      -> Frappe's own OAuth callback creates a Website User
      -> User.after_insert (es_social.social.utils.create_profile_for_user)
           * Social User role + Social Profile          (ES Social access)
      -> login -> on_session_creation (ensure_customer_on_login)
           * Individual Customer + Contact + portal user + Customer role
      -> redirected back to the page they came from

Customer provisioning deliberately runs at session creation rather than in
User.after_insert: Frappe's OAuth flow saves the same User document again
after inserting it, so touching the User from inside its own insert would
raise a TimestampMismatchError. It is idempotent, so it doubles as a retry on
every later login if the first attempt failed (e.g. a bad Customer Group).
"""

import frappe
from frappe.utils import cint

# Social Login Keys without a bundled icon fall back to these Frappe assets.
ICON_FALLBACKS = {
    "microsoft": "/assets/frappe/icons/social/office_365.svg",
    "outlook": "/assets/frappe/icons/social/office_365.svg",
}
LABEL_OVERRIDES = {"office_365": "Microsoft"}

SCOPE_SOCIAL = "Social login sign-ups"
SCOPE_ALL = "All website sign-ups"
SCOPE_OFF = "Off"


def _settings():
    return frappe.get_cached_doc("ES Social Settings")


# --------------------------------------------------------------------------- #
# Login providers
# --------------------------------------------------------------------------- #

def social_login_enabled():
    value = _settings().get("enable_social_login")
    return True if value is None else bool(cint(value))


def get_login_providers():
    """Enabled, fully-configured Social Login Keys — mirrors frappe/www/login.py.

    Returns only display data; the OAuth URL (and its single-use state token)
    is created on click by es_social.api.auth.social_login, so anonymous page
    views don't mint state tokens.
    """
    if not social_login_enabled():
        return []
    try:
        from frappe.utils.password import get_decrypted_password
    except Exception:
        return []

    out = []
    rows = frappe.get_all(
        "Social Login Key",
        filters={"enable_social_login": 1},
        fields=["name", "provider_name", "client_id", "icon"],
        order_by="provider_name asc",
    )
    for p in rows:
        if not p.client_id:
            continue
        if not get_decrypted_password("Social Login Key", p.name, "client_secret",
                                      raise_exception=False):
            continue
        key = p.name.lower()
        icon = p.icon
        if not icon:
            icon = next((v for k, v in ICON_FALLBACKS.items() if k in key), None)
        out.append({
            "name": p.name,
            "label": LABEL_OVERRIDES.get(key, p.provider_name or p.name),
            "icon": icon if icon and icon.startswith(("/", "https://")) else None,
        })
    return out


def is_enabled_provider(provider):
    return any(p["name"] == provider for p in get_login_providers())


# --------------------------------------------------------------------------- #
# Customer provisioning
# --------------------------------------------------------------------------- #

def erpnext_installed():
    return "erpnext" in frappe.get_installed_apps()


def customer_scope():
    return _settings().get("signup_customer_scope") or SCOPE_SOCIAL


def has_external_login(user):
    """True if the user has signed in with an external OAuth provider.
    (Frappe gives every user a placeholder "frappe" row, which doesn't count.)"""
    providers = frappe.get_all("User Social Login", filters={"parent": user}, pluck="provider")
    return any(p and p != "frappe" for p in providers)


def should_provision(user):
    """Does this website user qualify for an automatic ES ERP customer?"""
    if user in ("Guest", "Administrator") or not erpnext_installed():
        return False
    if frappe.db.get_value("User", user, "user_type") != "Website User":
        return False
    scope = customer_scope()
    if scope == SCOPE_OFF:
        return False
    if scope == SCOPE_ALL:
        return True
    return has_external_login(user)  # SCOPE_SOCIAL


def linked_customer(user):
    """Customer already tied to this user (portal user row or contact link)."""
    if frappe.get_meta("Customer").has_field("portal_users"):
        name = frappe.db.get_value("Portal User", {"parenttype": "Customer", "user": user}, "parent")
        if name:
            return name
    for contact in frappe.get_all("Contact", filters={"email_id": user}, pluck="name"):
        name = frappe.db.get_value(
            "Dynamic Link",
            {"parenttype": "Contact", "parent": contact, "link_doctype": "Customer"},
            "link_name",
        )
        if name:
            return name
    return None


def _default(doctype, setting_value, selling_field):
    """Settings value -> Selling Settings default -> tree root."""
    if setting_value and frappe.db.exists(doctype, setting_value):
        return setting_value
    value = frappe.db.get_single_value("Selling Settings", selling_field)
    if value:
        return value
    try:
        from frappe.utils.nestedset import get_root_of
        return get_root_of(doctype)
    except Exception:
        return None


def provision_customer(user):
    """Create (or reuse) an Individual Customer + Contact for *user*, link it
    as a portal user and grant the Customer role. Returns the customer name.
    Never raises — failures are logged and rolled back to a savepoint so the
    sign-in itself always succeeds."""
    if not erpnext_installed():
        return None
    savepoint = "es_social_customer"
    frappe.db.savepoint(savepoint)
    try:
        customer = linked_customer(user)
        if not customer:
            customer = _create_customer(user)
        _ensure_contact(user, customer)
        _grant_customer_role(user)
        return customer
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        frappe.log_error(frappe.get_traceback(), f"es_social: customer provisioning failed for {user}")
        return None


def _full_name(user):
    first, last, full = frappe.db.get_value(
        "User", user, ["first_name", "last_name", "full_name"]) or (None, None, None)
    return (full or " ".join(x for x in (first, last) if x) or user.split("@")[0]).strip()


def _create_customer(user):
    s = _settings()
    cust = frappe.new_doc("Customer")
    cust.customer_name = _full_name(user)
    cust.customer_type = "Individual"
    cust.customer_group = _default("Customer Group", s.get("signup_customer_group"), "customer_group")
    cust.territory = _default("Territory", s.get("signup_territory"), "territory")
    if cust.meta.has_field("email_id"):
        cust.email_id = user
    if cust.meta.has_field("portal_users"):
        cust.append("portal_users", {"user": user})
    cust.flags.ignore_mandatory = True
    cust.insert(ignore_permissions=True)
    return cust.name


def _ensure_contact(user, customer):
    name = frappe.db.get_value("Contact", {"email_id": user}, "name")
    if name:
        contact = frappe.get_doc("Contact", name)
        changed = False
        if not any(l.link_doctype == "Customer" and l.link_name == customer for l in contact.links):
            contact.append("links", {"link_doctype": "Customer", "link_name": customer})
            changed = True
        if contact.meta.has_field("user") and not contact.get("user"):
            contact.user = user
            changed = True
        if changed:
            contact.flags.ignore_mandatory = True
            contact.save(ignore_permissions=True)
    else:
        first, last = frappe.db.get_value("User", user, ["first_name", "last_name"]) or (None, None)
        contact = frappe.new_doc("Contact")
        contact.first_name = first or _full_name(user)
        contact.last_name = last
        contact.email_id = user
        if contact.meta.has_field("user"):
            contact.user = user
        contact.append("email_ids", {"email_id": user, "is_primary": 1})
        contact.append("links", {"link_doctype": "Customer", "link_name": customer})
        contact.flags.ignore_mandatory = True
        contact.insert(ignore_permissions=True)

    # keep the portal user link in place for customers created elsewhere
    cust = frappe.get_doc("Customer", customer)
    if cust.meta.has_field("portal_users") and not any(p.user == user for p in cust.portal_users):
        cust.append("portal_users", {"user": user})
        cust.flags.ignore_mandatory = True
        cust.save(ignore_permissions=True)


def _grant_customer_role(user):
    if not frappe.db.exists("Role", "Customer"):
        return
    if "Customer" in frappe.get_roles(user):
        return
    u = frappe.get_doc("User", user)
    u.flags.ignore_permissions = True
    u.add_roles("Customer")


def ensure_customer_on_login(login_manager=None):
    """on_session_creation hook: provision qualifying website users who don't
    have a customer yet. One or two indexed lookups when already linked."""
    try:
        user = getattr(login_manager, "user", None) or frappe.session.user
        if not should_provision(user) or linked_customer(user):
            return
        if provision_customer(user):
            frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "es_social: ensure_customer_on_login failed")


def backfill_customers():
    """`bench --site <site> execute es_social.social.signup.backfill_customers`
    — provision customers for existing website users who qualify under the
    current scope setting."""
    users = frappe.get_all("User", filters={"enabled": 1, "user_type": "Website User"}, pluck="name")
    made = 0
    for u in users:
        if not should_provision(u) or linked_customer(u):
            continue
        if provision_customer(u):
            made += 1
    frappe.db.commit()
    print(f"Provisioned {made} customers.")
