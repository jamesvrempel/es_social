# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Pages — business, brand and club pages (ES Social Settings → Enable Pages).

Pages are followed (one-way) rather than friended, always public, and can be
linked to an ES ERP Company / Customer / Supplier. Pages linked to a Company
are marked verified. Page admins can post *as* the page.
"""

import frappe
from frappe.utils import cint

from es_social.social.moderation import is_privileged
from es_social.social.utils import (
    GUEST, check_content, get_settings, get_viewer, require_login, scrub_for_guest, unique_slug,
)

CATEGORIES = ("Business", "Brand", "Club", "Community", "Organisation", "Event Series", "Other")
PAGE_FIELDS = ["name", "page_name", "slug", "category", "verified", "follower_count", "avatar",
               "cover_image", "about", "website", "location", "linked_doctype", "linked_name", "created_by"]


def _guard_enabled():
    if not cint(get_settings().get("enable_pages")):
        frappe.throw(frappe._("Pages are not enabled on this site."))


def is_page_admin(page, user=None):
    user = user or frappe.session.user
    if not page or user == GUEST:
        return False
    if is_privileged(user):
        return True
    return bool(frappe.db.exists("Social Page Admin", {"parent": page, "parenttype": "Social Page", "user": user})) \
        or frappe.db.get_value("Social Page", page, "created_by") == user


def _by_slug(slug):
    name = frappe.db.get_value("Social Page", {"slug": slug}, "name")
    if not name:
        frappe.throw(frappe._("Page not found."), frappe.DoesNotExistError)
    return name


def _verify_link(doctype, name, user):
    """Only allow linking ES ERP records the creator is actually related to."""
    if not doctype:
        return False
    if doctype not in ("Company", "Customer", "Supplier") or not name or not frappe.db.exists(doctype, name):
        frappe.throw(frappe._("Linked ES ERP record not found."))
    if is_privileged(user):
        return doctype == "Company"
    if doctype == "Customer":
        from es_social.social.signup import linked_customer
        if linked_customer(user) != name:
            frappe.throw(frappe._("You can only link your own customer account."), frappe.PermissionError)
        return False
    frappe.throw(frappe._("Only site admins can link a Company or Supplier."), frappe.PermissionError)


@frappe.whitelist()
def create_page(page_name, category="Business", about=None, website=None, location=None,
                avatar=None, cover_image=None, linked_doctype=None, linked_name=None):
    viewer = require_login()
    _guard_enabled()
    check_content(page_name)
    check_content(about)
    if category not in CATEGORIES:
        category = "Other"
    verified = _verify_link(linked_doctype, linked_name, viewer)
    doc = frappe.get_doc({
        "doctype": "Social Page", "page_name": page_name, "category": category,
        "slug": unique_slug(page_name, "Social Page", field="slug"),
        "about": about, "website": website, "location": location, "avatar": avatar,
        "cover_image": cover_image, "created_by": viewer,
        "linked_doctype": linked_doctype or None, "linked_name": linked_name or None,
        "verified": 1 if verified else 0,
        "admins": [{"user": viewer, "role": "Admin"}],
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"name": doc.name, "slug": doc.slug}


@frappe.whitelist()
def update_page(page, about=None, website=None, location=None, avatar=None, cover_image=None,
                category=None, page_name=None):
    viewer = require_login()
    if not is_page_admin(page, viewer):
        frappe.throw(frappe._("Page admins only."), frappe.PermissionError)
    doc = frappe.get_doc("Social Page", page)
    for f, v in (("about", about), ("website", website), ("location", location), ("avatar", avatar),
                 ("cover_image", cover_image), ("page_name", page_name)):
        if v is not None:
            if f in ("about", "page_name"):
                check_content(v)
            doc.set(f, v)
    if category in CATEGORIES:
        doc.category = category
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def set_page_admin(page, user, role="Admin", remove=0):
    viewer = require_login()
    if not is_page_admin(page, viewer):
        frappe.throw(frappe._("Page admins only."), frappe.PermissionError)
    doc = frappe.get_doc("Social Page", page)
    rows = [a for a in doc.admins if a.user != user]
    if cint(remove):
        if not rows:
            frappe.throw(frappe._("A page needs at least one admin."))
        doc.set("admins", [{"user": a.user, "role": a.role} for a in rows])
    else:
        if not frappe.db.exists("User", user):
            frappe.throw(frappe._("Member not found."))
        doc.set("admins", [{"user": a.user, "role": a.role} for a in rows] +
                [{"user": user, "role": role if role in ("Admin", "Editor") else "Admin"}])
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist(allow_guest=True)
def get_page(slug):
    viewer = get_viewer()
    name = _by_slug(slug)
    d = frappe.db.get_value("Social Page", name, PAGE_FIELDS, as_dict=True)
    d["is_admin"] = is_page_admin(name, viewer)
    d["following"] = viewer != GUEST and bool(
        frappe.db.exists("Social Page Follower", {"page": name, "user": viewer}))
    d["products"] = _linked_products(d) if d.linked_doctype == "Company" else []
    return scrub_for_guest(d, viewer)


def _linked_products(page):
    """Published ERPNext Website Items for Company-linked pages (best-effort)."""
    try:
        if not frappe.db.table_exists("Website Item"):
            return []
        return frappe.get_all("Website Item", filters={"published": 1},
                              fields=["web_item_name", "route", "website_image"],
                              order_by="ranking desc, modified desc", page_length=6)
    except Exception:
        return []


@frappe.whitelist(allow_guest=True)
def get_page_feed(slug, start=0, page_length=20):
    viewer = get_viewer()
    name = _by_slug(slug)
    from es_social.api.feed import POST_FIELDS, _list_posts, enrich_posts
    posts = _list_posts(viewer, {"is_deleted": 0, "page": name}, fields=POST_FIELDS,
                        order_by="posted_on desc", start=cint(start), page_length=cint(page_length) or 20)
    return enrich_posts(posts, viewer)


@frappe.whitelist()
def follow(page, follow=1):
    viewer = require_login()
    _guard_enabled()
    existing = frappe.db.get_value("Social Page Follower", {"page": page, "user": viewer}, "name")
    if cint(follow) and not existing:
        frappe.get_doc({"doctype": "Social Page Follower", "page": page, "user": viewer}).insert(ignore_permissions=True)
    elif not cint(follow) and existing:
        frappe.delete_doc("Social Page Follower", existing, ignore_permissions=True, force=True)
    frappe.db.sql("""update `tabSocial Page` p set follower_count =
                       (select count(*) from `tabSocial Page Follower` f where f.page=p.name) where p.name=%s""", page)
    frappe.db.commit()
    return {"following": bool(cint(follow)),
            "follower_count": frappe.db.get_value("Social Page", page, "follower_count")}


@frappe.whitelist(allow_guest=True)
def list_pages(query=None, category=None, start=0, page_length=24):
    get_viewer()
    filters = {}
    if category in CATEGORIES:
        filters["category"] = category
    or_filters = None
    if query:
        like = f"%{query}%"
        or_filters = {"page_name": ("like", like), "about": ("like", like)}
    return frappe.get_all("Social Page", filters=filters, or_filters=or_filters,
                          fields=["name", "page_name", "slug", "category", "verified", "follower_count", "avatar"],
                          order_by="verified desc, follower_count desc",
                          start=cint(start), page_length=min(cint(page_length) or 24, 100))


@frappe.whitelist(allow_guest=True)
def my_pages():
    viewer = get_viewer()
    if viewer == GUEST:
        return []
    names = set(frappe.get_all("Social Page Admin", filters={"user": viewer, "parenttype": "Social Page"},
                               pluck="parent"))
    names |= set(frappe.get_all("Social Page", filters={"created_by": viewer}, pluck="name"))
    if not names:
        return []
    return frappe.get_all("Social Page", filters={"name": ("in", list(names))},
                          fields=["name", "page_name", "slug", "avatar"])
