# Copyright (c) 2026, Enterprise Systems Australia and contributors
"""Visibility rules — the place a silent data leak would come from.

Run on a TEST site only:  bench --site <test-site> run-tests --app es_social
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from es_social.permissions.post import can_read_post
from es_social.social.moderation import clear_block_cache

USERS = ["es_t_alice@example.com", "es_t_bob@example.com", "es_t_carol@example.com"]


def _user(email):
    if not frappe.db.exists("User", email):
        frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0],
                        "user_type": "Website User", "send_welcome_email": 0}).insert(ignore_permissions=True)
        frappe.get_doc("User", email).add_roles("Social User")
    return email


def _post(author, **kw):
    frappe.set_user(author)
    doc = frappe.get_doc(dict({"doctype": "Social Post", "author": author, "content": "t",
                               "visibility": "Public", "approval_status": "Approved"}, **kw))
    doc.insert(ignore_permissions=True)
    frappe.set_user("Administrator")
    return doc.name


class TestVisibility(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for u in USERS:
            _user(u)
        cls.alice, cls.bob, cls.carol = USERS

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.delete("Social Block", {"blocker": ("in", USERS)})
        clear_block_cache(*USERS)

    def test_public_post_visible_to_guest(self):
        p = _post(self.alice)
        self.assertTrue(can_read_post(p, "Guest"))

    def test_friends_post_hidden_from_guest_and_strangers(self):
        p = _post(self.alice, visibility="Connections")
        self.assertFalse(can_read_post(p, "Guest"))
        self.assertFalse(can_read_post(p, self.bob))

    def test_only_me(self):
        p = _post(self.alice, visibility="Only Me")
        self.assertTrue(can_read_post(p, self.alice))
        self.assertFalse(can_read_post(p, self.bob))

    def test_pending_post_visible_to_author_only(self):
        p = _post(self.alice, approval_status="Pending")
        self.assertTrue(can_read_post(p, self.alice))
        self.assertFalse(can_read_post(p, self.bob))
        self.assertFalse(can_read_post(p, "Guest"))

    def test_block_hides_both_ways(self):
        p_alice = _post(self.alice)
        p_bob = _post(self.bob)
        frappe.get_doc({"doctype": "Social Block", "blocker": self.alice, "blocked": self.bob}).insert(ignore_permissions=True)
        clear_block_cache(self.alice, self.bob)
        self.assertFalse(can_read_post(p_bob, self.alice))
        self.assertFalse(can_read_post(p_alice, self.bob))
        self.assertTrue(can_read_post(p_alice, self.carol))

    def test_block_applies_to_list_queries(self):
        p_bob = _post(self.bob)
        frappe.get_doc({"doctype": "Social Block", "blocker": self.alice, "blocked": self.bob}).insert(ignore_permissions=True)
        clear_block_cache(self.alice, self.bob)
        frappe.set_user(self.alice)
        names = frappe.get_list("Social Post", filters={"name": p_bob}, pluck="name")
        frappe.set_user("Administrator")
        self.assertEqual(names, [])

    def test_closed_group_post_hidden_from_non_members(self):
        frappe.set_user(self.carol)
        g = frappe.get_doc({"doctype": "Social Group", "group_name": f"es-test-closed-{frappe.generate_hash(length=6)}",
                            "privacy": "Closed", "join_policy": "Approval Required"}).insert(ignore_permissions=True)
        frappe.set_user("Administrator")
        p = _post(self.carol, visibility="Group", group=g.name)
        self.assertTrue(can_read_post(p, self.carol))
        self.assertFalse(can_read_post(p, self.alice))
        self.assertFalse(can_read_post(p, "Guest"))

    def test_messages_private_to_participants(self):
        from es_social.permissions.private import conversation_conditions
        cond = conversation_conditions(self.alice)
        self.assertIn(self.alice, cond)
        self.assertEqual(conversation_conditions("Administrator"), "")
