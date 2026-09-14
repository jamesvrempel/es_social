# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime
from es_social.social.utils import bump


class SocialPhoto(Document):
    def before_insert(self):
        if not self.uploaded_by:
            self.uploaded_by = frappe.session.user
        if not self.posted_on:
            self.posted_on = now_datetime()

    def after_insert(self):
        bump("Social Album", self.album, "photo_count", 1)
        # first photo becomes the album cover if none set yet
        cover = frappe.db.get_value("Social Album", self.album, "cover_image")
        if not cover and self.image:
            frappe.db.set_value("Social Album", self.album, "cover_image", self.image,
                                update_modified=False)

    def on_trash(self):
        bump("Social Album", self.album, "photo_count", -1)
        # if this was the cover, replace with another remaining photo (or clear)
        cover = frappe.db.get_value("Social Album", self.album, "cover_image")
        if cover and cover == self.image:
            other = frappe.db.get_value(
                "Social Photo",
                {"album": self.album, "name": ("!=", self.name)},
                "image",
            )
            frappe.db.set_value("Social Album", self.album, "cover_image", other or "",
                                update_modified=False)
