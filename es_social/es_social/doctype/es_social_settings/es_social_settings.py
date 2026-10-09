# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ESSocialSettings(Document):
	def on_update(self):
		before = self.get_doc_before_save()
		was_on = bool(before and before.enable_fanout)
		if self.enable_fanout and not was_on:
			# build everyone's inboxes in the background; members keep the normal
			# feed until it finishes (see es_social.social.fanout.read_enabled)
			frappe.db.set_single_value("ES Social Settings", "fanout_ready_since", None)
			frappe.enqueue("es_social.social.fanout.backfill", queue="long", timeout=3600,
			               enqueue_after_commit=True, days=30)
			frappe.msgprint(frappe._("Building feed inboxes in the background. Members keep the normal "
			                          "feed until this finishes."), alert=True)
		elif not self.enable_fanout and was_on:
			frappe.db.set_single_value("ES Social Settings", "fanout_ready_since", None)
