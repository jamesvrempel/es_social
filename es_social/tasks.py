# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Scheduled maintenance jobs."""

import frappe


def reconcile_counts():
    """Heal counter drift by re-deriving from source tables (atomic)."""
    # post reactions
    frappe.db.sql(
        """
        update `tabSocial Post` p
        set p.like_count = (
            select count(*) from `tabSocial Reaction` r
            where r.reference_doctype='Social Post' and r.reference_name = p.name
        ),
        p.comment_count = (
            select count(*) from `tabSocial Comment` c
            where c.reference_post = p.name and c.is_deleted = 0
        )
        """
    )
    # comment reactions
    frappe.db.sql(
        """
        update `tabSocial Comment` c
        set c.like_count = (
            select count(*) from `tabSocial Reaction` r
            where r.reference_doctype='Social Comment' and r.reference_name = c.name
        )
        """
    )
    # group membership
    frappe.db.sql(
        """
        update `tabSocial Group` g
        set g.member_count = (
            select count(*) from `tabSocial Group Member` m
            where m.group = g.name and m.status = 'Active'
        )
        """
    )
    # profile stats
    frappe.db.sql(
        """
        update `tabSocial Profile` sp
        set sp.post_count = (
            select count(*) from `tabSocial Post` p
            where p.author = sp.user and p.is_deleted = 0
        )
        """
    )
    frappe.db.commit()


def recompute_trending():
    """Hourly: trending scores (see es_social.social.ranking)."""
    from es_social.social.ranking import recompute_trending as run
    run()


def hourly():
    """Event reminders + email digests (digests act once a day at the set hour)."""
    from es_social.api.events import send_reminders
    from es_social.social.digest import send_digests
    for job in (send_reminders, send_digests):
        try:
            job()
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"es_social: {job.__name__} failed")


def daily():
    """Affinity decay, feed-inbox trimming, counter reconciliation for pages/events."""
    from es_social.social import fanout, ranking
    for job in (ranking.decay_affinity, fanout.trim_inboxes, reconcile_phase_counts):
        try:
            job()
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"es_social: {job.__name__} failed")


def reconcile_phase_counts():
    frappe.db.sql("""update `tabSocial Page` p set follower_count =
                     (select count(*) from `tabSocial Page Follower` f where f.page = p.name)""")
    frappe.db.sql("""update `tabSocial Event` e set
                     going_count = (select count(*) from `tabSocial Event RSVP` r where r.event=e.name and r.status='Going'),
                     interested_count = (select count(*) from `tabSocial Event RSVP` r where r.event=e.name and r.status='Interested')""")
    frappe.db.commit()
