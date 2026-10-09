# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Event posts: create, RSVP, upcoming list, calendar (.ics), reminders and
optional paid events (draft ERPNext Sales Order on RSVP "Going")."""

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from es_social.social.utils import GUEST, get_settings, get_viewer, notify, require_login

RSVP_STATUSES = ("Going", "Interested", "Not Going")


def _guard_enabled():
    v = get_settings().get("enable_events")
    if v is not None and not cint(v):
        frappe.throw(frappe._("Events are disabled on this site."))


@frappe.whitelist()
def create_event(title, starts_on, ends_on=None, venue=None, online_url=None, description=None,
                 capacity=0, group=None, page=None, visibility=None, item=None, timezone=None):
    """Creates the Social Event and its announcement post in one step."""
    viewer = require_login()
    _guard_enabled()
    if not title or not starts_on:
        frappe.throw(frappe._("An event needs a title and a start time."))
    start = get_datetime(starts_on)
    end = get_datetime(ends_on) if ends_on else None
    if end and end < start:
        frappe.throw(frappe._("The event can't end before it starts."))
    if online_url and not str(online_url).startswith(("https://", "http://")):
        frappe.throw(frappe._("The online link must start with https://"))
    if item:
        from es_social.social.moderation import is_privileged
        from es_social.api.pages import is_page_admin
        # only site admins or page admins may attach a priced item
        if not (is_privileged(viewer) or (page and is_page_admin(page, viewer))):
            frappe.throw(frappe._("Only site or page admins can create paid events."), frappe.PermissionError)
        if "erpnext" not in frappe.get_installed_apps() or not frappe.db.exists("Item", item):
            frappe.throw(frappe._("Item {0} not found in ES ERP.").format(item))

    ev = frappe.get_doc({
        "doctype": "Social Event", "title": title, "organizer": viewer,
        "starts_on": start, "ends_on": end, "timezone": timezone or "Australia/Perth",
        "venue": venue, "online_url": online_url, "description": description,
        "capacity": max(cint(capacity), 0), "group": group, "page": page, "item": item,
    })
    ev.insert(ignore_permissions=True)

    from es_social.api.posts import _create_post
    post = _create_post(content=description or "", visibility=visibility, group=group,
                        page=page, event=ev.name)
    frappe.db.set_value("Social Event", ev.name, "post", post["name"], update_modified=False)
    frappe.db.commit()
    return post


def _event_visible(event, viewer):
    from es_social.permissions.post import can_read_post
    post = frappe.db.get_value("Social Event", event, "post")
    return bool(post) and can_read_post(post, viewer)


@frappe.whitelist()
def rsvp(event, status):
    viewer = require_login()
    _guard_enabled()
    if status not in RSVP_STATUSES:
        frappe.throw(frappe._("Unknown response."))
    if not _event_visible(event, viewer):
        frappe.throw(frappe._("Event not found."), frappe.PermissionError)
    ev = frappe.db.get_value("Social Event", event,
                             ["name", "status", "capacity", "going_count", "starts_on", "item", "organizer"],
                             as_dict=True)
    if ev.status == "Cancelled":
        frappe.throw(frappe._("This event has been cancelled."))
    existing = frappe.db.get_value("Social Event RSVP", {"event": event, "user": viewer},
                                   ["name", "status", "sales_order"], as_dict=True)
    previous = existing.status if existing else None
    if status == "Going" and previous != "Going" and cint(ev.capacity) and cint(ev.going_count) >= cint(ev.capacity):
        frappe.throw(frappe._("Sorry, this event is full."))

    if existing:
        frappe.db.set_value("Social Event RSVP", existing.name, "status", status)
        name = existing.name
    else:
        name = frappe.get_doc({"doctype": "Social Event RSVP", "event": event, "user": viewer,
                               "status": status}).insert(ignore_permissions=True).name

    _recount(event)
    result = {"ok": True, "my_rsvp": status}
    if status == "Going" and previous != "Going" and ev.item and not (existing and existing.sales_order):
        so = _create_sales_order(viewer, ev.item, event)
        if so:
            frappe.db.set_value("Social Event RSVP", name, "sales_order", so)
            result["sales_order"] = so
    if status == "Going" and previous != "Going":
        title = frappe.db.get_value("Social Event", event, "title")
        actor = frappe.db.get_value("User", viewer, "full_name") or "Someone"
        notify(ev.organizer, frappe._("{0} is going to {1}").format(actor, title),
               reference_doctype="Social Event", reference_name=event)
    frappe.db.commit()
    counts = frappe.db.get_value("Social Event", event, ["going_count", "interested_count"], as_dict=True)
    result.update(counts)
    return result


def _recount(event):
    frappe.db.sql(
        """update `tabSocial Event` e set
             going_count = (select count(*) from `tabSocial Event RSVP` r where r.event=e.name and r.status='Going'),
             interested_count = (select count(*) from `tabSocial Event RSVP` r where r.event=e.name and r.status='Interested')
           where e.name=%s""", event)


def _create_sales_order(user, item, event):
    """Draft Sales Order for the member's ES ERP customer. Never blocks the RSVP."""
    try:
        from es_social.social.signup import linked_customer, provision_customer
        customer = linked_customer(user) or provision_customer(user)
        if not customer:
            return None
        so = frappe.new_doc("Sales Order")
        so.customer = customer
        so.transaction_date = frappe.utils.today()
        so.delivery_date = get_datetime(frappe.db.get_value("Social Event", event, "starts_on")).date()
        so.append("items", {"item_code": item, "qty": 1})
        title = frappe.db.get_value("Social Event", event, "title")
        if so.meta.has_field("remarks"):
            so.remarks = f"ES Social event: {title}"
        so.flags.ignore_permissions = True
        so.insert()
        return so.name
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"es_social: event sales order failed for {user}")
        return None


@frappe.whitelist(allow_guest=True)
def upcoming(group=None, page=None, limit=10):
    """Upcoming events the viewer can see (public ones for guests)."""
    viewer = get_viewer()
    filters = {"starts_on": (">=", add_to_date(now_datetime(), hours=-3)), "status": "Scheduled"}
    if group:
        filters["group"] = group
    if page:
        filters["page"] = page
    rows = frappe.get_all("Social Event", filters=filters,
                          fields=["name", "title", "starts_on", "venue", "online_url", "going_count",
                                  "interested_count", "post", "group", "page"],
                          order_by="starts_on asc", page_length=100)
    from es_social.permissions.post import can_read_post
    out = []
    for r in rows:
        if r.post and can_read_post(r.post, viewer):
            r["starts_on"] = str(r.starts_on)
            out.append(r)
        if len(out) >= min(cint(limit) or 10, 50):
            break
    return out


@frappe.whitelist()
def cancel_event(event):
    viewer = require_login()
    ev = frappe.db.get_value("Social Event", event, ["organizer", "title"], as_dict=True)
    from es_social.social.moderation import is_privileged
    if not ev or (ev.organizer != viewer and not is_privileged(viewer)):
        frappe.throw(frappe._("Only the organizer can cancel this event."), frappe.PermissionError)
    frappe.db.set_value("Social Event", event, "status", "Cancelled")
    for u in frappe.get_all("Social Event RSVP", filters={"event": event, "status": ("in", ["Going", "Interested"])},
                            pluck="user"):
        notify(u, frappe._("{0} has been cancelled").format(ev.title),
               reference_doctype="Social Event", reference_name=event)
    frappe.db.commit()
    return {"ok": True}


def _ics_escape(text):
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def ics(event):
    """Add-to-calendar download (times exported in UTC)."""
    viewer = get_viewer()
    if not frappe.db.exists("Social Event", event) or not _event_visible(event, viewer):
        frappe.throw(frappe._("Event not found."), frappe.DoesNotExistError)
    ev = frappe.get_doc("Social Event", event)
    import pytz
    tz = pytz.timezone(frappe.utils.get_system_timezone())

    def utc(dt):
        return tz.localize(get_datetime(dt)).astimezone(pytz.utc).strftime("%Y%m%dT%H%M%SZ")

    end = ev.ends_on or add_to_date(ev.starts_on, hours=2)
    url = frappe.utils.get_url(f"/social?event={ev.name}")
    location = ev.venue or ev.online_url or ""
    body = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ES Social//Events//EN", "BEGIN:VEVENT",
        f"UID:{ev.name}@{frappe.local.site}", f"DTSTAMP:{utc(now_datetime())}",
        f"DTSTART:{utc(ev.starts_on)}", f"DTEND:{utc(end)}",
        f"SUMMARY:{_ics_escape(ev.title)}", f"LOCATION:{_ics_escape(location)}",
        f"DESCRIPTION:{_ics_escape(frappe.utils.strip_html(ev.description or '') + ' ' + url)}",
        f"URL:{url}",
        "STATUS:CANCELLED" if ev.status == "Cancelled" else "STATUS:CONFIRMED",
        "END:VEVENT", "END:VCALENDAR", "",
    ])
    frappe.local.response.filename = f"{frappe.scrub(ev.title)[:40] or 'event'}.ics"
    frappe.local.response.filecontent = body
    frappe.local.response.type = "download"
    frappe.local.response.content_type = "text/calendar"


def send_reminders():
    """Hourly: remind Going/Interested members ~24h before an event starts."""
    now = now_datetime()
    events = frappe.get_all("Social Event",
                            filters={"status": "Scheduled", "reminder_sent": 0,
                                     "starts_on": ("between", [add_to_date(now, hours=23), add_to_date(now, hours=25)])},
                            fields=["name", "title", "starts_on"])
    for ev in events:
        when = frappe.format(ev.starts_on, "Datetime")
        for u in frappe.get_all("Social Event RSVP",
                                filters={"event": ev.name, "status": ("in", ["Going", "Interested"])}, pluck="user"):
            notify(u, frappe._("Reminder: {0} starts {1}").format(ev.title, when),
                   reference_doctype="Social Event", reference_name=ev.name)
        frappe.db.set_value("Social Event", ev.name, "reminder_sent", 1, update_modified=False)
    frappe.db.commit()
