# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from es_social.social.utils import unique_slug


class SocialProfile(Document):
    def validate(self):
        if not self.display_name:
            self.display_name = frappe.db.get_value("User", self.user, "full_name") or self.user
        if not self.profile_slug:
            self.profile_slug = unique_slug(self.display_name, "Social Profile", exclude=self.name)

    def get_public_dict(self):
        return {
            "user": self.user,
            "display_name": self.display_name,
            "profile_slug": self.profile_slug,
            "headline": self.headline,
            "profile_image": self.profile_image,
            "cover_image": self.cover_image,
            "bio": self.bio,
            "location": self.location,
            "website": self.website,
            "connection_count": self.connection_count,
            "post_count": self.post_count,
        }
