# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Short-lived Redis cache for anonymous reads (public timeline, trending,
public profiles). Guests all see the same thing, so crawlers and bots are
served from cache instead of the database. Members are never cached."""

import hashlib
import json
import time

import frappe
from frappe.utils import cint


def _ttl():
    from es_social.social.utils import get_settings
    return cint(get_settings().get("guest_cache_seconds") or 0)


def guest_cached(viewer, key, producer, **kwargs):
    ttl = _ttl()
    if viewer != "Guest" or ttl <= 0:
        return producer()
    digest = hashlib.sha1(json.dumps(kwargs, sort_keys=True, default=str).encode()).hexdigest()[:16]
    ck = f"es_social:guest:{key}:{digest}"
    cache = frappe.cache()
    hit = cache.get_value(ck)
    if hit is not None:
        return hit
    value = producer()
    cache.set_value(ck, value, expires_in_sec=ttl)
    return value


class FeedTimer:
    """Logs feed reads slower than ES Social Settings → Log Feeds Slower Than
    to logs/es_social.log — the measurement that decides whether fan-out is
    ever needed."""

    def __init__(self, name, viewer):
        self.name, self.viewer = name, viewer

    def __enter__(self):
        self.t0 = time.monotonic()
        return self

    def __exit__(self, *exc):
        from es_social.social.utils import get_settings
        ms = (time.monotonic() - self.t0) * 1000
        limit = cint(get_settings().get("log_slow_feeds_ms") or 0)
        if limit and ms > limit:
            frappe.logger("es_social").warning(
                f"slow feed {self.name} {ms:.0f}ms viewer={'guest' if self.viewer == 'Guest' else 'member'}")
        return False
