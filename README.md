# ES Social

A public social network module for **Frappe / ERPNext v15** — profiles, a
relationship‑aware feed, reactions, comments, connections (friends) and groups —
delivered as a standard installable Frappe app so it drops onto any ES ERP site.

Built as a **real Frappe app** (not Server Scripts), so none of the
RestrictedPython sandbox limits apply: the logic lives in ordinary whitelisted
Python with `@frappe.whitelist()` endpoints.

---

## Features (v0.5.0)

- **Video links** — paste a **YouTube or Vimeo** URL in the composer (🎬 Video)
  or add one to an album (🎬 Add video). Links are validated against a strict
  provider allowlist and rendered as an embedded player in the feed, album grid
  (▶ tile) and lightbox. Videos and photos are mutually exclusive per post.
- **Albums hold mixed media** — `Social Photo` now carries a `media_type`
  (Image / Video); albums mix uploaded photos and video links, and a video's
  thumbnail can auto-become the album cover.
- **Upload improvements** — the size limit is driven by *ES Social Settings →
  max upload size* (no more hardcoded 5 MB), oversize/failed uploads now report
  a clear per-file message, and the Photos page has a direct **＋ Upload photos**
  button (creates a photo post that lands in your gallery).
- **Albums** — user-created named albums (`Social Album`) with their own privacy,
  own page at `/social/album/<slug>`, cover, edit/delete, per-photo delete.
- **Photo gallery** — Photos page (`/social/photos`) with a full-screen lightbox.
- **Photos on posts** — attach images to a post, set profile avatar and cover.
- **Profiles** — auto‑provisioned for every website user, with avatar, cover,
  bio, work/education history and vanity URLs at `/u/<slug>`.
- **Feed** — query‑on‑read, newest‑first, with relationship‑based visibility
  (`Public` / `Connections` / `Only Me` / `Group`) enforced at the row level via
  `permission_query_conditions` **and** `has_permission`.
- **Reactions** — seven types (Like, Love, Care, Haha, Wow, Sad, Angry), one per
  user per item, upserted server‑side.
- **Comments** — threaded (one level of replies), with notifications.
- **Connections** — friend requests, accept/decline, unfriend, block; a unique
  `pair_key` prevents duplicate edges; connection sets are Redis‑cached.
- **Groups** — Public / Closed / Secret, open or approval‑based joining, group
  feeds, member roles (Member / Moderator / Admin).
- **Moderation** — content reporting queue + keyword filter + per‑minute rate
  limits, configurable in **ES Social Settings**.
- **Portal UI** — self‑contained pages at `/social`, `/social/groups`,
  `/social/connections` and `/u/<slug>` (no desk licence needed for members).

## Roles

| Role | Purpose | Desk access |
|------|---------|-------------|
| `Social User` | Standard member | No |
| `Social Moderator` | Reviews reports, moderates content | Yes |
| `Social Admin` | Manages settings, groups, pages | Yes |

New website users automatically receive **Social User** and a **Social Profile**
(toggle with *Allow Public Signup* in ES Social Settings).

---

## Install

```bash
cd ~/frappe-bench

# fetch the app
bench get-app es_social https://github.com/jamesvrempel/es_social

# install onto a site
bench --site your-site.local install-app es_social

# build the portal assets
bench build --app es_social
bench --site your-site.local clear-cache
```

### Backfill existing users

To create profiles and grant the member role to users that already exist:

```bash
bench --site your-site.local execute es_social.install.backfill_profiles
```

### Enable public sign‑up (optional)

For an open network, turn on sign‑up in **Website Settings → “Allow sign‑up”**.
Members land on `/social` after logging in.

---

## Architecture notes

- **Visibility** is computed in `es_social/permissions/post.py` and reused for
  comments through a subquery. All identifiers are passed through
  `frappe.db.escape` — no raw string interpolation into SQL.
- **Counters** (`like_count`, `comment_count`, `member_count`, …) are maintained
  with atomic `UPDATE … greatest(0, x ± 1)` writes and healed nightly by
  `es_social.tasks.reconcile_counts`.
- **Reactions** are polymorphic via a Dynamic Link (`reference_doctype` +
  `reference_name`) so the same table serves posts and comments.
- **Connection sets** are cached in Redis (TTL 300s) and invalidated whenever a
  connection is accepted, removed or blocked.
- **Feed** is query‑on‑read for v1. Fan‑out‑on‑write and an EdgeRank‑style
  `score` field are stubbed in `tasks.recompute_trending` for a later phase.

## API surface

All under `es_social.api.*`, all `@frappe.whitelist()`:

- `feed.get_feed`, `feed.get_profile_feed`, `feed.get_group_feed`
- `posts.create_post` / `edit_post` / `delete_post` / `share_post` / `react` /
  `unreact` / `get_reactions` / `report_content`
- `comments.add_comment` / `delete_comment` / `list_comments`
- `connections.send_request` / `respond_request` / `unfriend` / `block` /
  `list_connections` / `pending_requests` / `connection_status`
- `groups.create_group` / `join_group` / `leave_group` / `approve_member` /
  `list_my_groups` / `discover_groups` / `get_group`
- `profile.get_profile` / `update_profile` / `search_people`

## Roadmap

- **Phase 2** — richer group admin, event posts, photo albums.
- **Phase 3** — direct messaging (`enable_messaging`), Pages (`enable_pages`).
- **Phase 4** — fan‑out feed + trending/EdgeRank ranking.
- **Phase 5** — notification digests, moderation dashboards, GraphQL‑style batch reads.

## Licence

MIT © 2026 Enterprise Systems Australia Pty Ltd
