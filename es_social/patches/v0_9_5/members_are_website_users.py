# Copyright (c) 2026, Enterprise Systems Australia and contributors
"""v0.9.5: Social User must not grant Desk access, and members who became
System Users only because of it are turned back into Website Users.

Anyone holding another role with Desk Access (System Manager, Accounts User,
Social Moderator, etc.) is left as a System User.
"""

import frappe


def execute():
    from es_social.install import ensure_member_role_is_website_only
    ensure_member_role_is_website_only()

    desk_roles = set(frappe.get_all("Role", filters={"desk_access": 1}, pluck="name"))
    members = frappe.get_all("Has Role", filters={"role": "Social User", "parenttype": "User"}, pluck="parent")
    fixed = []
    for user in set(members):
        if user in ("Administrator", "Guest"):
            continue
        if frappe.db.get_value("User", user, "user_type") != "System User":
            continue
        roles = set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))
        if roles & desk_roles:
            continue  # genuinely staff: keep Desk access
        frappe.db.set_value("User", user, "user_type", "Website User", update_modified=False)
        fixed.append(user)
    frappe.db.commit()
    if fixed:
        # their sessions were issued as System Users; make them sign in again
        from frappe.sessions import clear_sessions
        for user in fixed:
            try:
                clear_sessions(user=user, force=True)
            except Exception:
                pass
        frappe.clear_cache()
    print(f"es_social: {len(fixed)} member(s) changed to Website User")
