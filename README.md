# ES Social

A public social network module for **Frappe / ERPNext v15** — profiles, a
relationship‑aware feed, reactions, comments, connections (friends) and groups —
delivered as a standard installable Frappe app so it drops onto any ES ERP site.

Built as a **real Frappe app** (not Server Scripts), so none of the
RestrictedPython sandbox limits apply: the logic lives in ordinary whitelisted
Python with `@frappe.whitelist()` endpoints.

---

## v0.9.6

- Repackaged release of v0.9.5 as a clean, self-contained version (no code
  changes beyond the version number).

## v0.9.5

- **Fix: new members were becoming System Users.** Frappe auto-created the
  *Social User* role with **Desk Access** on (before ES Social's own setup could
  turn it off), and any role with Desk Access makes a user a System User. The
  role is now forced to no Desk Access on every migrate, and existing members
  whose *only* desk-granting role was Social User are converted to Website
  Users (they'll be asked to sign in again). Staff with other desk roles are
  left alone.

## v0.9.4

- **Branding:** the "ES Social" name is now configurable in
  **/app/es-social-settings → Branding → Site Name Shown As**:
  *Website name* (Website Settings → App Name, falling back to the domain),
  *Domain name* (the address the visitor is on — handy when one site serves
  several domains), or *Custom*. It replaces "ES Social" in the top bar, page
  titles, the join prompt, digest emails, notifications and the unsubscribe page.

## v0.9.3

- **Cache-busting:** ES Social's CSS/JS links now carry the app version
  (`es_social.js?v=0.9.3`), so each release is fetched fresh past Cloudflare's
  year-long asset cache — no more manual cache purges after updates.

## v0.9.2

- **Photo mosaic** — photos are no longer cropped to squares. Feed posts,
  albums and the Photos page use a justified mosaic: rows of near-equal height
  where each photo's width follows its real proportions (portraits stay tall,
  panoramas stay wide). The last row isn't stretched; layout re-flows on resize.
- A **single photo** in a post is shown at its actual size and proportions
  (scaled down to fit, never enlarged).
- Feed photos now open in the **lightbox**; posts with more than 6 photos show
  "+N" on the last tile.
- Tune row heights with `--row-h` in `es_social.css` (`.es-mosaic` 220px,
  `.es-media-mosaic` 190px; smaller on phones).

## v0.9.1

- **Fix:** with *Enable Fan-out Feed* switched on before its inboxes were built,
  members' home feeds were empty. Members now only read from inboxes once the
  backfill has finished (*Fan-out Inboxes Built* is stamped in settings), and an
  empty inbox always falls back to the normal feed. Turning fan-out on now runs
  the backfill automatically in the background.
- **Top** sort widens beyond 7 days on quiet sites instead of showing nothing.

## v0.9.0 — roadmap phases 2–5

> **Big release — test on demo2 before production.** `bench migrate` adds 14
> DocTypes, new fields, feed indexes and a Desk dashboard.

### Phase 2 — groups, events, albums, member safety
- **Group admin** (Admin tab on the group page): promote/demote Admin ·
  Moderator · Member, remove, ban/unban, approve/decline join requests, group
  rules, cover, privacy and joining policy. Making a group *more* visible
  (Secret → Closed → Public) asks for confirmation because it exposes earlier
  posts; making it more private is always allowed. The last admin can't leave
  or be demoted; banned members can't rejoin.
- **Post approval** per group (pending posts are visible only to the author
  and group admins) and **pin to top** (pins apply to the group feed only).
- **Invite links** with expiry and use limits — they skip the join request but
  never a ban.
- **Events** — 📅 Event button in the feed, group and page composers; RSVP
  Going / Interested / Not Going with capacity; Add-to-calendar (.ics);
  reminders 24 h before; organiser can cancel (attendees are notified).
  **Paid events**: site or page admins can attach an ES ERP Item code — an RSVP
  of *Going* raises a **draft** Sales Order for the member's customer account.
- **Albums** — drag to reorder, ★ to set the cover, **group albums** any member
  can add to (and delete their own photos from).
- **Blocking** (⋯ on a profile or post) hides posts and comments both ways and
  stops friend requests, comments, reactions and messages. Existing
  "Blocked" connections are migrated automatically.
- **Report member**, plus reports on pages and messages.
- **Suspension** — suspended members can browse but every write action is
  refused; timed suspensions lift themselves.

### Phase 3 — messaging & Pages
- **Direct messages** (Settings → *Enable Messaging*) at `/social/messages`:
  one-to-one threads, unread badge in the top bar, live updates (falls back to
  polling), report a message. Members choose who can message them — friends
  (default), anyone, or no one. Threads are private to the two participants,
  even in Desk; moderators only ever see an individually *reported* message.
- **Raven**: set *Messaging Provider = Raven* (with the Raven app installed)
  and the Message button hands off to Raven instead. The DM deep link is
  best-effort — check it against your Raven version.
- **Pages** (Settings → *Enable Pages*) at `/social/pages` and `/p/<slug>`:
  business / brand / club pages that people **follow**; admins post *as* the
  page and can run page events. Pages linked to an ES ERP **Company** (site
  admins only) get a ✔ verified badge and show published Website Items;
  members may link their own Customer record.

### Phase 4 — feed performance & ranking
- **Indexes** on the feed's hot paths, and feeds slower than *Log Feeds Slower
  Than (ms)* are written to `logs/es_social.log` — that log decides whether
  fan-out is ever needed.
- **Trending** sidebar (guests too), scored hourly: reactions + 2×commenters +
  3×shares with time decay; distinct people only, authors' own activity ignored,
  accounts younger than *Trending: Min Account Age* excluded.
- **Latest / Top** toggle on the home feed. Latest (default) is chronological;
  Top re-ranks the last 7 days by engagement × how much you interact with each
  author (affinity decays 10 %/day).
- **Fan-out feed** (off by default — *Enable Fan-out Feed*): posts are written
  to friends' / group members' / followers' inboxes by a background job;
  authors or pages above the *Celebrity Threshold* are pulled at read time;
  inboxes trimmed nightly. After enabling run
  `bench --site <site> execute es_social.social.fanout.backfill`.
  Note: with fan-out on, the member home feed becomes "friends, groups and
  pages you follow" rather than every public post.

### Phase 5 — digests, moderation, batch reads, caching
- **Email digests** — daily (at *Send Digests At*, site time) or weekly
  (Mondays), per-category choices and message-privacy on `/social/settings`,
  one-click unsubscribe in every email (Spam Act 2003).
- **Moderation** at `/social/moderation` (site moderators see everything; group
  admins see their own groups): reports grouped per item, one-click hide /
  restore / dismiss / warn / suspend / ban-from-group, pending-post approvals,
  headline stats. Every action is written to **Social Moderation Log**.
  Content is **auto-hidden** after *N* distinct reports pending review, and the
  keyword filter can **hold for review** instead of rejecting.
  Desk dashboard: `/app/dashboard-view/ES Social Moderation`.
- **Batch reads** — `es_social.api.batch.get` runs up to 10 allow-listed read
  calls in one request with the caller's own permissions.
- **Guest caching** — the public timeline, trending and public reads are cached
  for *Guest Cache (seconds)*; members are never cached.

### Upgrade
```bash
./update_bench.sh <site>     # pull, migrate, build, clear cache, restart
```
Then: enable Messaging / Pages in **ES Social Settings** if wanted, give your
moderators the **Social Moderator** role, purge the Cloudflare cache, and make
sure the scheduler is running (`bench --site <site> scheduler status`) —
trending, reminders and digests depend on it.

### Tests
`bench --site <test-site> run-tests --app es_social` (a test site — the suite
creates users and posts) covers guest / friends / only-me / pending / blocked /
closed-group visibility and message privacy.

## v0.8.1

- Comments are always expanded under each post (no click needed), with a
  **View all N comments** link when a post has more than the 2 shown.
- Comments sit in a light blue panel (`--es-comments-bg: #e7f3ff` in
  `es_social.css` — change that one variable to retheme).
- New comments now append to the comment list (previously landed inside the
  input row).

## What's new in v0.8.0 — sign in with Google, Microsoft, etc.

Guests can join in one click with any **Google, Microsoft, GitHub** (or other
OAuth2/OpenID) account. A new member immediately gets:

- **ES Social access** — `Social User` role and a Social Profile (avatar seeded
  from their Google photo), and
- **an ES ERP customer account** — an *Individual* **Customer**, a linked
  **Contact**, a **Portal User** link and the **Customer** role, so they can use
  the ERPNext customer portal (orders, invoices, quotes) as a Website User.

"Continue with …" buttons appear in the guest sidebar card and in the join
prompt on every write action, and bring the visitor back to the page they were
on. Buttons are built from whichever **Social Login Keys** are enabled on the
site, so each site can offer different providers.

### Settings (ES Social Settings → Sign-in & Customer Accounts)

| Setting | Default | |
|---|---|---|
| Show Social Sign-in Buttons | on | |
| Create ES ERP Customer For | Social login sign-ups | or *All website sign-ups* / *Off* |
| Customer Group for Sign-ups | blank | blank → Selling Settings default → root |
| Territory for Sign-ups | blank | blank → Selling Settings default → root |

Provisioning runs on login (`on_session_creation`), is idempotent (reuses an
existing Contact/Customer for the email), and never blocks the sign-in —
failures roll back to a savepoint and go to the Error Log, then retry on the
next login. Existing members: `bench --site <site> execute
es_social.social.signup.backfill_customers`.

### One-time setup per site

1. **Website Settings** → untick *Disable Signup* (or set *Sign ups = Allow* on
   each Social Login Key).
2. **Google** — Google Cloud Console → APIs & Services → Credentials → OAuth
   client ID (Web application). Authorised redirect URI:
   `https://<site>/api/method/frappe.integrations.oauth2_logins.login_via_google`.
   In Frappe: *Social Login Key → New → Social Login Provider: Google*, paste
   Client ID/Secret, tick *Enable Social Login*.
3. **Microsoft (work/school *and* personal Outlook/Hotmail accounts)** —
   Microsoft Entra → App registrations → New, *Supported account types:
   Accounts in any organizational directory and personal Microsoft accounts*.
   Frappe's built-in "Office 365" preset uses the v1 endpoint, which only
   accepts work/school accounts, so add a **Custom** Social Login Key instead:
   - Provider Name `Microsoft` → redirect URI to register in Entra:
     `https://<site>/api/method/frappe.integrations.oauth2_logins.custom/microsoft`
   - Base URL `https://graph.microsoft.com`, API Endpoint `oidc/userinfo`
   - Authorize URL `https://login.microsoftonline.com/common/oauth2/v2.0/authorize`
   - Access Token URL `https://login.microsoftonline.com/common/oauth2/v2.0/token`
   - Auth URL Data `{"response_type": "code", "scope": "openid email profile"}`
   - User ID Property `sub`
4. **ES Social Settings** → choose the Customer Group / Territory for sign-ups.
5. Leave **Portal Settings → Default Role** blank (ES Social assigns Customer
   itself); if it is set to Customer, ERPNext's own hook may create the
   customer first — ES Social then reuses it and adds the portal-user link.

Upgrade: `bench --site <site> migrate && bench build --app es_social`.

## What's new in v0.7.0 — browse without an account

The social area is now **open to read without signing up**. An account is only
required to **post** (and to comment, react, share, join groups, add friends or
upload photos).

| Visitor can… | Guest | Member |
|---|---|---|
| Read the public timeline at `/social` | ✅ | ✅ |
| View profiles at `/u/<slug>` and their public posts | ✅ | ✅ |
| View public albums, photos and the lightbox | ✅ | ✅ |
| Browse groups and read **Public** group feeds | ✅ | ✅ |
| Read comments on visible posts | ✅ | ✅ |
| Search people | ✅ | ✅ |
| Post, comment, react, share, upload | ❌ → join prompt | ✅ |
| Join groups, add friends, see requests / friends list | ❌ → join prompt | ✅ |

How it works:

- Read endpoints are `@frappe.whitelist(allow_guest=True)` and resolve the
  viewer with `get_viewer()`; every write endpoint still calls `require_login()`.
- Guests hold no DocPerms, so guest reads use explicit **public-only** queries
  (`visibility = 'Public'`, `privacy = 'Public'`) rather than relaxing role
  permissions. `Connections`, `Only Me`, Closed and Secret content stays hidden.
- **No member email addresses are sent to guests** — `author`, `user`,
  `owner_user`, `created_by` etc. are stripped from guest payloads, and guests
  look profiles up by public slug only. Work/education history is omitted for
  guests.
- Write buttons stay visible; for guests they open a "Join ES Social" prompt
  with Sign up / Log in (login returns you to the page you were on).
- `/social/connections` remains members-only.
- Posts inside a **Public** group are now readable by non-members (previously
  the row-level rules hid them even though the group page was open). Commenting
  on a group post still requires membership.
- Shared posts now only embed the original if the viewer is allowed to see it.

Settings (**ES Social Settings**):

- **Allow Guest Browsing** (default on) — untick to restore the old
  login-required behaviour site-wide.
- **Sign-up URL** (default `/login#signup`) — where guest "Sign up" buttons go,
  e.g. an approval-gated signup page.

Upgrade: `bench --site <site> migrate && bench build --app es_social`
(the `v0_7.enable_guest_browsing` patch seeds the new settings). Frappe's own
**Website Settings → Disable Signup** must be unticked if you use the built-in
sign-up page.

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

Phases 2–5 shipped in v0.9.0 (see above). Candidates next: threaded comment
replies in the UI, @mentions, photo tagging with consent/removal, group chats
in messaging, a mobile-friendly PWA shell.

## Licence

MIT © 2026 Enterprise Systems Australia Pty Ltd
