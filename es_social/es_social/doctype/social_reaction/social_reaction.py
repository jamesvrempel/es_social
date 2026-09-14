# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from es_social.social.utils import bump, notify

COUNT_FIELD = "like_count"


class SocialReaction(Document):
    def before_insert(self):
        if not self.user:
            self.user = frappe.session.user
        # one reaction per user per item — the API handles upsert; this guards direct inserts
        existing = frappe.db.get_value(
            "Social Reaction",
            {"reference_doctype": self.reference_doctype,
             "reference_name": self.reference_name,
             "user": self.user},
            "name",
        )
        if existing:
            frappe.throw(
                frappe._("You've already reacted to this."),
                exc=frappe.DuplicateEntryError,
            )

    def after_insert(self):
        bump(self.reference_doctype, self.reference_name, COUNT_FIELD, 1)
        if self.reference_doctype == "Social Post":
            owner = frappe.db.get_value("Social Post", self.reference_name, "author")
            actor = frappe.db.get_value("User", self.user, "full_name") or self.user
            if owner and owner != self.user:
                notify(owner,
                       frappe._("{0} reacted to your post").format(actor),
                       reference_doctype="Social Post", reference_name=self.reference_name,
                       link="/social")

    def on_trash(self):
        bump(self.reference_doctype, self.reference_name, COUNT_FIELD, -1)
