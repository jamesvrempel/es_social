# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime
from es_social.social.utils import get_or_create_profile, bump, get_settings


class SocialPost(Document):
    def before_insert(self):
        if not self.author:
            self.author = frappe.session.user
        if not self.posted_on:
            self.posted_on = now_datetime()
        if not self.visibility:
            self.visibility = get_settings().default_visibility or "Public"
        profile = get_or_create_profile(self.author)
        if profile:
            self.author_profile = profile.name
        if self.visibility == "Group" and not self.group:
            frappe.throw(frappe._("A group post must specify a group."))
        if self.video_url and (not self.post_type or self.post_type == "Status"):
            self.post_type = "Video"

    def after_insert(self):
        if self.author_profile:
            bump("Social Profile", self.author_profile, "post_count", 1)
        if self.post_type == "Shared" and self.shared_post:
            bump("Social Post", self.shared_post, "share_count", 1)

    def on_trash(self):
        if self.author_profile:
            bump("Social Profile", self.author_profile, "post_count", -1)
        if self.post_type == "Shared" and self.shared_post:
            bump("Social Post", self.shared_post, "share_count", -1)
