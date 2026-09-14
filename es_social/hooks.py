# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

app_name = "es_social"
app_title = "ES Social"
app_publisher = "Enterprise Systems Australia"
app_description = "Public social network module for Frappe / ERPNext"
app_email = "james@enterprisesystems.com.au"
app_license = "MIT"
app_version = "0.6.0"

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
after_install = "es_social.install.after_install"

# ---------------------------------------------------------------------------
# Document events
# ---------------------------------------------------------------------------
doc_events = {
    "User": {
        "after_insert": "es_social.social.utils.create_profile_for_user",
    },
}

# ---------------------------------------------------------------------------
# Row-level permissions (relationship-based visibility)
# ---------------------------------------------------------------------------
permission_query_conditions = {
    "Social Post": "es_social.permissions.post.get_permission_query_conditions",
    "Social Comment": "es_social.permissions.comment.get_permission_query_conditions",
    "Social Album": "es_social.permissions.album.get_permission_query_conditions",
    "Social Photo": "es_social.permissions.album.get_photo_permission_query_conditions",
}

has_permission = {
    "Social Post": "es_social.permissions.post.has_permission",
    "Social Album": "es_social.permissions.album.has_permission",
}

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
scheduler_events = {
    "hourly_long": [
        "es_social.tasks.recompute_trending",
    ],
    "daily_long": [
        "es_social.tasks.reconcile_counts",
    ],
}

# ---------------------------------------------------------------------------
# Website / portal routing
# ---------------------------------------------------------------------------
website_route_rules = [
    {"from_route": "/u/<slug>", "to_route": "social/profile"},
    {"from_route": "/social/group/<slug>", "to_route": "social/group"},
    {"from_route": "/social/album/<slug>", "to_route": "social/album"},
]

# Fixtures — ship the roles so a fresh install has them even before after_install runs
fixtures = [
    {
        "dt": "Role",
        "filters": [["name", "in", ["Social User", "Social Moderator", "Social Admin"]]],
    }
]
