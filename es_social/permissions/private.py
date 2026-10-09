# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Direct messages are private to their two participants — even in Desk.

Only Administrator bypasses this (for support/legal requests); moderators see
reported messages individually through the moderation queue."""

import frappe


def conversation_conditions(user=None):
    user = user or frappe.session.user
    if user == "Administrator":
        return ""
    u = frappe.db.escape(user)
    return f"(`tabSocial Conversation`.user_a = {u} or `tabSocial Conversation`.user_b = {u})"


def message_conditions(user=None):
    user = user or frappe.session.user
    if user == "Administrator":
        return ""
    u = frappe.db.escape(user)
    return ("`tabSocial Message`.conversation in (select c.name from `tabSocial Conversation` c "
            f"where c.user_a = {u} or c.user_b = {u})")
