# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime
from es_social.social.utils import bump, notify


class SocialComment(Document):
    def before_insert(self):
        if not self.author:
            self.author = frappe.session.user
        if not self.posted_on:
            self.posted_on = now_datetime()

    def after_insert(self):
        bump("Social Post", self.reference_post, "comment_count", 1)
        post_author = frappe.db.get_value("Social Post", self.reference_post, "author")
        actor = frappe.db.get_value("User", self.author, "full_name") or self.author
        if post_author and post_author != self.author:
            notify(post_author,
                   frappe._("{0} commented on your post").format(actor),
                   reference_doctype="Social Post", reference_name=self.reference_post,
                   link="/social")
        if self.parent_comment:
            parent_author = frappe.db.get_value("Social Comment", self.parent_comment, "author")
            if parent_author and parent_author not in (self.author, post_author):
                notify(parent_author,
                       frappe._("{0} replied to your comment").format(actor),
                       reference_doctype="Social Post", reference_name=self.reference_post,
                       link="/social")

    def on_trash(self):
        bump("Social Post", self.reference_post, "comment_count", -1)
