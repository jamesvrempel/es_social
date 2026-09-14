# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime
from es_social.social.utils import unique_slug


class SocialAlbum(Document):
    def before_insert(self):
        if not self.owner_user:
            self.owner_user = frappe.session.user
        if not self.posted_on:
            self.posted_on = now_datetime()
        if not self.slug:
            self.slug = unique_slug(self.title, "Social Album", field="slug")

    def get_public_dict(self):
        return {
            "name": self.name,
            "title": self.title,
            "slug": self.slug,
            "description": self.description,
            "cover_image": self.cover_image,
            "privacy": self.privacy,
            "photo_count": self.photo_count,
            "owner_user": self.owner_user,
            "posted_on": str(self.posted_on),
        }
