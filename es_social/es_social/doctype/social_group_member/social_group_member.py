# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime
from es_social.social.utils import bump


class SocialGroupMember(Document):
    def before_insert(self):
        if not self.joined_on:
            self.joined_on = now_datetime()
        dup = frappe.db.get_value(
            "Social Group Member", {"group": self.group, "user": self.user}, "name"
        )
        if dup:
            frappe.throw(frappe._("This user is already a member of the group."))

    def after_insert(self):
        if self.status == "Active":
            bump("Social Group", self.group, "member_count", 1)

    def on_update(self):
        before = self.get_doc_before_save()
        if before and before.status != self.status:
            if self.status == "Active" and before.status != "Active":
                bump("Social Group", self.group, "member_count", 1)
            elif self.status != "Active" and before.status == "Active":
                bump("Social Group", self.group, "member_count", -1)

    def on_trash(self):
        if self.status == "Active":
            bump("Social Group", self.group, "member_count", -1)
