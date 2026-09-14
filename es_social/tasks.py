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
    """Placeholder for Phase 4 EdgeRank-style scoring.

    A future `score` field on Social Post can be filled here with
    engagement + recency-decay so the feed can offer a 'Top posts' sort.
    """
    pass
