# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime
from es_social.social.utils import (
    pair_key,
    clear_connection_cache,
    bump,
    notify,
    get_or_create_profile,
)


class SocialConnection(Document):
    def validate(self):
        if self.from_user == self.to_user:
            frappe.throw(frappe._("You cannot connect with yourself."))
        self.pair_key = pair_key(self.from_user, self.to_user)
        if self.is_new():
            self.requested_on = now_datetime()
            dup = frappe.db.get_value(
                "Social Connection",
                {"pair_key": self.pair_key, "name": ("!=", self.name or "")},
                ["name", "status"],
                as_dict=True,
            )
            if dup:
                frappe.throw(frappe._("A connection between these users already exists ({0}).").format(dup.status))

    def on_update(self):
        old_status = self.get_doc_before_save().status if self.get_doc_before_save() else None
        if self.status == "Accepted" and old_status != "Accepted":
            if not self.responded_on:
                self.db_set("responded_on", now_datetime(), update_modified=False)
            clear_connection_cache(self.from_user, self.to_user)
            for u, other in ((self.from_user, self.to_user), (self.to_user, self.from_user)):
                p = get_or_create_profile(u)
                if p:
                    bump("Social Profile", p.name, "connection_count", 1)
            other_name = frappe.db.get_value("User", self.to_user, "full_name") or self.to_user
            notify(self.from_user,
                   frappe._("{0} accepted your connection request").format(other_name),
                   reference_doctype="Social Connection", reference_name=self.name)

    def after_insert(self):
        requester = frappe.db.get_value("User", self.from_user, "full_name") or self.from_user
        notify(self.to_user,
               frappe._("{0} sent you a connection request").format(requester),
               reference_doctype="Social Connection", reference_name=self.name,
               link="/social/connections")

    def on_trash(self):
        if self.status == "Accepted":
            clear_connection_cache(self.from_user, self.to_user)
            for u in (self.from_user, self.to_user):
                name = frappe.db.get_value("Social Profile", {"user": u}, "name")
                if name:
                    bump("Social Profile", name, "connection_count", -1)
