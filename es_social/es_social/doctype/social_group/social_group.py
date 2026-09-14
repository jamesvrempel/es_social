# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime
from es_social.social.utils import unique_slug


class SocialGroup(Document):
    def before_insert(self):
        if not self.created_by:
            self.created_by = frappe.session.user
        if not self.slug:
            self.slug = unique_slug(self.group_name, "Social Group", field="slug")

    def after_insert(self):
        # creator becomes the first Admin member
        member = frappe.get_doc({
            "doctype": "Social Group Member",
            "group": self.name,
            "user": self.created_by,
            "role": "Admin",
            "status": "Active",
            "joined_on": now_datetime(),
        })
        member.insert(ignore_permissions=True)
