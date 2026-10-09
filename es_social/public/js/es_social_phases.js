/* ES Social — roadmap phases 2-5 (events, group admin, safety, messaging,
 * pages, trending, settings, moderation).
 * Copyright (c) 2026, Enterprise Systems Australia and contributors
 * Loaded after es_social.js; plugs into window.ES hooks.
 */
(function () {
  "use strict";
  var ES = window.ES;
  if (!ES) return;
  ES.hooks = ES.hooks || {};
  ES.pages = ES.pages || {};
  var esc = function (s) { return ES.esc(s == null ? "" : String(s)); };
  var $ = function (id) { return document.getElementById(id); };

  // ---- small utilities -----------------------------------------------------
  function parseDT(s) { return s ? new Date(String(s).replace(" ", "T")) : null; }
  function fmtDT(s, opts) {
    var d = parseDT(s);
    if (!d || isNaN(d)) return "";
    return d.toLocaleString("en-AU", opts || { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  }
  function toServerDT(v) { return v ? v.replace("T", " ") + (v.length === 16 ? ":00" : "") : null; }
  // frappe.call already shows the server's own error dialog; only speak up
  // when the server couldn't be reached at all.
  function fail(e) { if (!e || !(e.responseJSON || e.responseText)) alert("Couldn't reach the server. Please try again."); }

  // ---- modal ----------------------------------------------------------------
  ES.modal = function (title, bodyHtml, opts) {
    opts = opts || {};
    var overlay = document.createElement("div");
    overlay.className = "es-modal";
    overlay.innerHTML = '<div class="es-modal-box' + (opts.wide ? " es-modal-wide" : "") + '" role="dialog" aria-modal="true">' +
      '<button class="es-modal-x" title="Close">\u2715</button><h3>' + esc(title) + "</h3>" +
      '<div class="es-modal-body">' + bodyHtml + "</div></div>";
    function close() { if (overlay.parentNode) overlay.parentNode.removeChild(overlay); document.removeEventListener("keydown", key); }
    function key(e) { if (e.key === "Escape") close(); }
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay || e.target.closest(".es-modal-x") || e.target.closest("[data-close]")) close();
    });
    document.addEventListener("keydown", key);
    document.body.appendChild(overlay);
    var first = overlay.querySelector("input,textarea,select");
    if (first) first.focus();
    return { el: overlay, close: close };
  };

  // ---- popover menu -----------------------------------------------------------
  ES.menu = function (anchor, items) {
    var old = document.querySelector(".es-popmenu"); if (old) old.remove();
    var m = document.createElement("div");
    m.className = "es-popmenu";
    m.innerHTML = items.map(function (it, i) {
      return '<button data-i="' + i + '"' + (it.danger ? ' class="danger"' : "") + ">" + esc(it.label) + "</button>";
    }).join("");
    document.body.appendChild(m);
    var r = anchor.getBoundingClientRect();
    m.style.top = (window.scrollY + r.bottom + 4) + "px";
    m.style.left = Math.max(8, window.scrollX + r.right - m.offsetWidth) + "px";
    function away(e) { if (!m.contains(e.target)) { m.remove(); document.removeEventListener("click", away, true); } }
    setTimeout(function () { document.addEventListener("click", away, true); }, 0);
    m.addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      m.remove(); document.removeEventListener("click", away, true);
      items[parseInt(b.dataset.i, 10)].action();
    });
  };

  // ---- reporting -----------------------------------------------------------------
  var REASONS = ["Spam", "Harassment", "Hate Speech", "Nudity", "Violence", "Misinformation", "Other"];
  ES.openReport = function (doctype, name, what) {
    var md = ES.modal("Report " + (what || "content"),
      '<label class="es-label">Why are you reporting this?</label>' +
      '<select class="es-input" id="es-rep-reason">' + REASONS.map(function (r) { return "<option>" + r + "</option>"; }).join("") + "</select>" +
      '<label class="es-label">Anything else moderators should know? (optional)</label>' +
      '<textarea class="es-input" id="es-rep-details" rows="3"></textarea>' +
      '<div class="es-modal-actions"><button class="es-btn" data-close>Cancel</button>' +
      '<button class="es-btn es-btn-primary" id="es-rep-send">Send report</button></div>');
    md.el.querySelector("#es-rep-send").onclick = function () {
      ES.call("posts.report_content", {
        reference_doctype: doctype, reference_name: name,
        reason: md.el.querySelector("#es-rep-reason").value,
        details: md.el.querySelector("#es-rep-details").value
      }).then(function () { md.close(); alert("Thanks — a moderator will review this."); })
        .catch(function (e) { fail(e); });
    };
  };

  // ---- post menu (report / pin / delete) -------------------------------------
  ES.openPostMenu = function (post, anchor) {
    var name = post.dataset.name, items = [];
    var own = post.dataset.canEdit === "1";
    if (ES.state.mode === "group" && ES.state.canModerateGroup) {
      var pinned = post.dataset.pinned === "1";
      items.push({ label: pinned ? "Unpin" : "Pin to top of group", action: function () {
        ES.call("group_admin.pin_post", { post: name, pinned: pinned ? 0 : 1 }).then(function () { location.reload(); });
      } });
    }
    if (own) {
      items.push({ label: "Delete post", danger: true, action: function () {
        if (!confirm("Delete this post?")) return;
        ES.call("posts.delete_post", { name: name }).then(function () { post.remove(); });
      } });
    } else {
      items.push({ label: "Report post", action: function () { ES.openReport("Social Post", name, "post"); } });
      if (post.dataset.authorSlug) {
        items.push({ label: "Block this member", danger: true, action: function () {
          if (!confirm("Block this member? You won't see each other's posts and they can't contact you.")) return;
          ES.call("safety.block_user", { slug: post.dataset.authorSlug }).then(function () {
            document.querySelectorAll('.es-post[data-author-slug="' + post.dataset.authorSlug + '"]').forEach(function (p) { p.remove(); });
          });
        } });
      }
    }
    ES.menu(anchor, items);
  };

  // ---- events --------------------------------------------------------------------
  ES.renderEvent = function (ev) {
    var d = parseDT(ev.starts_on);
    var mon = d ? d.toLocaleString("en-AU", { month: "short" }).toUpperCase() : "";
    var day = d ? d.getDate() : "";
    var where = ev.venue ? esc(ev.venue) : (ev.online_url ? '<a href="' + esc(ev.online_url) + '" target="_blank" rel="noopener">Online event</a>' : "");
    var cancelled = ev.status === "Cancelled";
    var btns = cancelled ? '<span class="es-badge-pill es-badge-warn">Cancelled</span>' :
      ["Going", "Interested", "Not Going"].map(function (s) {
        var full = s === "Going" && ev.full && ev.my_rsvp !== "Going";
        return '<button class="es-btn es-rsvp' + (ev.my_rsvp === s ? " active" : "") + '" data-status="' + s + '"' +
          (full ? " disabled title=\"Event is full\"" : "") + ">" + (s === "Going" ? "✓ " : s === "Interested" ? "★ " : "") + s + "</button>";
      }).join("");
    return '<div class="es-event" data-event="' + esc(ev.name) + '">' +
      '<div class="es-event-date"><span>' + esc(mon) + "</span><b>" + esc(day) + "</b></div>" +
      '<div class="es-event-body"><div class="es-event-title">' + esc(ev.title) +
      (ev.paid ? ' <span class="es-badge-pill">Paid</span>' : "") + (ev.full && !cancelled ? ' <span class="es-badge-pill es-badge-warn">Full</span>' : "") + "</div>" +
      '<div class="es-muted">' + esc(fmtDT(ev.starts_on)) + (ev.ends_on ? " – " + esc(fmtDT(ev.ends_on, { hour: "numeric", minute: "2-digit" })) : "") +
      (where ? " · " + where : "") + "</div>" +
      '<div class="es-muted es-event-counts">' + (ev.going_count || 0) + " going · " + (ev.interested_count || 0) + " interested" +
      (ev.capacity ? " · " + ev.capacity + " places" : "") + "</div>" +
      '<div class="es-event-actions">' + btns +
      ' <a class="es-btn es-btn-link" href="/api/method/es_social.api.events.ics?event=' + encodeURIComponent(ev.name) + '">📅 Add to calendar</a></div>' +
      "</div></div>";
  };

  ES.openEventForm = function (extra) {
    extra = extra || {};
    var md = ES.modal("Create event",
      '<label class="es-label">Title</label><input class="es-input" id="ev-title" maxlength="140">' +
      '<div class="es-row2"><div><label class="es-label">Starts</label><input class="es-input" type="datetime-local" id="ev-start"></div>' +
      '<div><label class="es-label">Ends (optional)</label><input class="es-input" type="datetime-local" id="ev-end"></div></div>' +
      '<label class="es-label">Venue</label><input class="es-input" id="ev-venue" placeholder="e.g. Walpole Visitor Centre">' +
      '<label class="es-label">Online link (optional)</label><input class="es-input" id="ev-url" placeholder="https://…">' +
      '<div class="es-row2"><div><label class="es-label">Capacity (0 = unlimited)</label><input class="es-input" type="number" min="0" id="ev-cap" value="0"></div>' +
      (extra.group || extra.page ? "<div></div>" :
        '<div><label class="es-label">Who can see it</label><select class="es-input" id="ev-vis"><option value="Public">🌐 Public</option><option value="Connections">👥 Friends</option></select></div>') +
      "</div>" +
      '<label class="es-label">Details</label><textarea class="es-input" id="ev-desc" rows="3"></textarea>' +
      '<details class="es-muted"><summary>Paid event (admins)</summary><label class="es-label">ES ERP Item Code</label>' +
      '<input class="es-input" id="ev-item" placeholder="Leave blank for a free event"></details>' +
      '<div class="es-modal-actions"><button class="es-btn" data-close>Cancel</button><button class="es-btn es-btn-primary" id="ev-save">Create event</button></div>',
      { wide: true });
    md.el.querySelector("#ev-save").onclick = function () {
      var g = function (id) { var el = md.el.querySelector("#" + id); return el ? el.value.trim() : ""; };
      if (!g("ev-title") || !g("ev-start")) { alert("Please add a title and start time."); return; }
      var args = { title: g("ev-title"), starts_on: toServerDT(g("ev-start")), ends_on: toServerDT(g("ev-end")),
        venue: g("ev-venue"), online_url: g("ev-url"), capacity: g("ev-cap") || 0, description: g("ev-desc"),
        item: g("ev-item") || null };
      if (extra.group) args.group = extra.group;
      if (extra.page) args.page = extra.page;
      if (!extra.group && !extra.page) args.visibility = g("ev-vis") || "Public";
      this.disabled = true;
      var btn = this;
      ES.call("events.create_event", args).then(function (p) {
        md.close();
        var feed = $("es-feed");
        if (feed) feed.insertAdjacentHTML("afterbegin", ES.renderPost(p));
        if (p.pending) alert("Thanks — your event will appear once it's approved.");
      }).catch(function (e) { btn.disabled = false; fail(e); });
    };
  };

  // ---- home feed extras: sort tabs, trending, upcoming --------------------------
  function initFeedExtras() {
    var tabs = $("es-sort-tabs");
    if (tabs) tabs.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-sort]"); if (!b || b.classList.contains("active")) return;
      tabs.querySelectorAll("button").forEach(function (x) { x.classList.toggle("active", x === b); });
      ES.state.sort = b.dataset.sort;
      ES.resetFeed(); ES.loadFeed();
    });
    ES.call("feed.get_trending", { limit: 5 }).then(function (rows) {
      if (!rows || !rows.length) return;
      $("es-trending").hidden = false;
      $("es-trending-body").innerHTML = rows.map(function (r) {
        var who = r.page_slug ? '<a href="/p/' + esc(r.page_slug) + '">' + esc(r.author_name) + "</a>"
          : r.author_slug ? '<a href="/u/' + esc(r.author_slug) + '">' + esc(r.author_name) + "</a>" : esc(r.author_name);
        return '<div class="es-trend"><div class="es-trend-snip">' + esc(r.snippet || "(photo)") + "</div>" +
          '<div class="es-muted">' + who + " · " + (r.like_count || 0) + " reactions · " + (r.comment_count || 0) + " comments</div></div>";
      }).join("");
    }).catch(function () {});
    if ($("es-upcoming")) loadUpcoming({}, $("es-upcoming"), $("es-upcoming-body"));
  }

  function loadUpcoming(args, card, body) {
    args.limit = args.limit || 5;
    return ES.call("events.upcoming", args).then(function (rows) {
      if (!rows || !rows.length) { if (body && card && card.id !== "es-upcoming") body.innerHTML = '<div class="es-muted">No upcoming events.</div>'; return; }
      if (card) card.hidden = false;
      body.innerHTML = rows.map(function (r) {
        return '<div class="es-upc"><b>' + esc(fmtDT(r.starts_on)) + "</b><div>" + esc(r.title) + "</div>" +
          '<div class="es-muted">' + (r.going_count || 0) + " going" + (r.venue ? " · " + esc(r.venue) : "") + "</div></div>";
      }).join("");
    }).catch(function () {});
  }

  // ---- profile: message / block / report ----------------------------------------
  ES.hooks.profileLoaded = function (pf) {
    var mb = $("es-msg-btn");
    if (mb) mb.onclick = function () {
      if (ES.needsAccount("Sign up or log in to send messages.")) return;
      ES.call("messages.start_conversation", { slug: pf.profile_slug }).then(function (r) {
        location.href = r.provider === "Raven" ? r.url : "/social/messages?c=" + encodeURIComponent(r.conversation);
      }).catch(function (e) { fail(e); });
    };
    var more = $("es-profile-more");
    if (more) more.onclick = function () {
      if (ES.needsAccount()) return;
      var items = [];
      if (pf.i_blocked) items.push({ label: "Unblock", action: function () {
        ES.call("safety.unblock_user", { slug: pf.profile_slug }).then(function () { location.reload(); });
      } });
      else items.push({ label: "Block", danger: true, action: function () {
        if (!confirm("Block " + pf.display_name + "? You won't see each other's posts, and they can't message, friend or comment on your posts.")) return;
        ES.call("safety.block_user", { slug: pf.profile_slug }).then(function () { location.reload(); });
      } });
      items.push({ label: "Report member", action: function () { ES.openReport("User", pf.profile_slug, "member"); } });
      ES.menu(more, items);
    };
  };

  // ---- group tabs + admin --------------------------------------------------------
  ES.hooks.groupLoaded = function (g) {
    ES.state.canModerateGroup = !!g.can_admin;
    var tabs = $("es-group-tabs"), panel = $("es-group-panel");
    if (!tabs) return;
    tabs.hidden = false;
    if (!ES.flags.events) { var et = tabs.querySelector('[data-tab="events"]'); if (et) et.remove(); }
    if (g.can_admin) {
      var at = $("es-admin-tab"); at.hidden = false;
      var n = (g.pending_members || 0) + (g.pending_posts || 0);
      if (n) at.innerHTML = 'Admin <span class="es-badge">' + n + "</span>";
    }
    if (g.rules) {
      var head = $("es-group-head");
      if (head) head.insertAdjacentHTML("beforeend", '<details class="es-rules"><summary>Group rules</summary><div>' + esc(g.rules).replace(/\n/g, "<br>") + "</div></details>");
    }
    var feedEls = [$("es-feed"), $("es-feed-sentinel"), $("es-group-composer")];
    var composerWasVisible = $("es-group-composer") && $("es-group-composer").style.display !== "none";
    tabs.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-tab]"); if (!b) return;
      tabs.querySelectorAll("button").forEach(function (x) { x.classList.toggle("active", x === b); });
      var isFeed = b.dataset.tab === "feed";
      feedEls.forEach(function (el, i) { if (!el) return; if (i === 2) el.style.display = isFeed && composerWasVisible ? "" : "none"; else el.hidden = !isFeed; });
      panel.hidden = isFeed;
      if (!isFeed) ({ members: groupMembers, albums: groupAlbums, events: groupEvents, admin: groupAdmin })[b.dataset.tab](g, panel);
    });
  };

  function memberRow(m, actions) {
    var link = m.profile_slug ? '<a href="/u/' + esc(m.profile_slug) + '">' + esc(m.display_name) + "</a>" : esc(m.display_name);
    return '<div class="es-member" data-user="' + esc(m.user || "") + '" data-member="' + esc(m.member) + '">' +
      ES.avatar(m.profile_image, m.display_name, "es-avatar-sm") + "<div class=\"es-member-name\">" + link +
      (m.role !== "Member" ? ' <span class="es-badge-pill">' + esc(m.role) + "</span>" : "") + "</div>" + (actions || "") + "</div>";
  }

  function groupMembers(g, panel) {
    panel.innerHTML = '<div class="es-card"><div class="es-muted">Loading…</div></div>';
    ES.call("group_admin.list_members", { group: g.name }).then(function (rows) {
      panel.innerHTML = '<div class="es-card"><div class="es-card-title">' + rows.length + " members</div>" +
        rows.map(function (m) { return memberRow(m); }).join("") + "</div>";
    }).catch(function () { panel.innerHTML = '<div class="es-card es-muted">Members are visible to group members only.</div>'; });
  }

  function groupAlbums(g, panel) {
    panel.innerHTML = '<div class="es-card"><div class="es-card-title">Group albums' +
      (g.is_member ? ' <button class="es-btn es-btn-primary es-right" id="es-new-galbum">+ New album</button>' : "") +
      '</div><div class="es-album-grid" id="es-galbums"><div class="es-muted">Loading…</div></div></div>';
    ES.call("albums.list_group_albums", { group: g.name }).then(function (rows) {
      $("es-galbums").innerHTML = rows.length ? rows.map(function (a) {
        return '<a class="es-album-card" href="/social/album/' + esc(a.slug) + '"><div class="es-album-cover"' +
          (a.cover_image ? ' style="background-image:url(' + esc(a.cover_image) + ')"' : "") + "></div>" +
          "<div><b>" + esc(a.title) + '</b><div class="es-muted">' + (a.photo_count || 0) + " photos</div></div></a>";
      }).join("") : '<div class="es-muted">No albums yet.</div>';
    });
    var nb = $("es-new-galbum");
    if (nb) nb.onclick = function () {
      var t = prompt("Album name:"); if (!t) return;
      ES.call("albums.create_album", { title: t, group: g.name }).then(function (a) { location.href = "/social/album/" + a.slug; });
    };
  }

  function groupEvents(g, panel) {
    panel.innerHTML = '<div class="es-card"><div class="es-card-title">Upcoming events</div><div id="es-gevents"><div class="es-muted">Loading…</div></div></div>';
    loadUpcoming({ group: g.name, limit: 20 }, null, $("es-gevents"));
  }

  function groupAdmin(g, panel) {
    panel.innerHTML =
      '<div class="es-card"><div class="es-card-title">Posts awaiting approval</div><div id="ga-posts" class="es-muted">Loading…</div></div>' +
      '<div class="es-card"><div class="es-card-title">Join requests</div><div id="ga-pending" class="es-muted">Loading…</div></div>' +
      '<div class="es-card"><div class="es-card-title">Members & roles</div><div id="ga-members" class="es-muted">Loading…</div></div>' +
      '<div class="es-card"><div class="es-card-title">Invite links <button class="es-btn es-right" id="ga-newinv">+ New link</button></div><div id="ga-invites"></div></div>' +
      '<div class="es-card"><div class="es-card-title">Banned</div><div id="ga-banned" class="es-muted">—</div></div>' +
      (g.my_role === "Admin" || !g.my_role ? '<div class="es-card"><div class="es-card-title">Group settings</div><div id="ga-settings"></div></div>' : "");
    var reload = function () { groupAdmin(g, panel); };

    ES.call("moderation.pending_posts", { group: g.name }).then(function (posts) {
      $("ga-posts").innerHTML = posts.length ? posts.map(function (p) {
        return '<div class="es-pending-item" data-post="' + esc(p.name) + '">' + ES.renderPost(p) +
          '<div class="es-modal-actions"><button class="es-btn" data-d="reject">Reject</button><button class="es-btn es-btn-primary" data-d="approve">Approve</button></div></div>';
      }).join("") : '<span class="es-muted">Nothing waiting.</span>';
      $("ga-posts").querySelectorAll("[data-d]").forEach(function (b) {
        b.onclick = function () {
          var it = b.closest(".es-pending-item");
          var notes = b.dataset.d === "reject" ? (prompt("Reason (sent to the author, optional):") || "") : "";
          ES.call("moderation.review_post", { post: it.dataset.post, decision: b.dataset.d, notes: notes }).then(function () { it.remove(); });
        };
      });
    }).catch(function () { $("ga-posts").textContent = "—"; });

    ES.call("group_admin.list_members", { group: g.name, status: "Pending" }).then(function (rows) {
      $("ga-pending").innerHTML = rows.length ? rows.map(function (m) {
        return memberRow(m, '<button class="es-btn es-btn-primary" data-a="approve">Approve</button><button class="es-btn" data-a="reject">Decline</button>');
      }).join("") : '<span class="es-muted">No requests.</span>';
      $("ga-pending").querySelectorAll("[data-a]").forEach(function (b) {
        b.onclick = function () {
          var row = b.closest(".es-member");
          ES.call(b.dataset.a === "approve" ? "groups.approve_member" : "group_admin.reject_member", { member: row.dataset.member }).then(function () { row.remove(); });
        };
      });
    });

    ES.call("group_admin.list_members", { group: g.name }).then(function (rows) {
      $("ga-members").innerHTML = rows.map(function (m) {
        var roleSel = g.my_role === "Admin" || !g.my_role
          ? '<select data-a="role">' + ["Member", "Moderator", "Admin"].map(function (r) { return "<option" + (r === m.role ? " selected" : "") + ">" + r + "</option>"; }).join("") + "</select>"
          : "";
        return memberRow(m, roleSel + '<button class="es-btn" data-a="remove">Remove</button><button class="es-btn" data-a="ban">Ban</button>');
      }).join("");
      $("ga-members").querySelectorAll("[data-a]").forEach(function (el) {
        var row = el.closest(".es-member"), user = row.dataset.user;
        if (el.dataset.a === "role") el.onchange = function () {
          ES.call("group_admin.set_role", { group: g.name, user: user, role: el.value }).catch(function (e) { fail(e); reload(); });
        };
        else el.onclick = function () {
          var ban = el.dataset.a === "ban";
          if (!confirm(ban ? "Ban this member? They'll be removed and can't rejoin." : "Remove this member from the group?")) return;
          ES.call(ban ? "group_admin.ban_member" : "group_admin.remove_member", { group: g.name, user: user })
            .then(reload).catch(function (e) { fail(e); });
        };
      });
    });

    ES.call("group_admin.list_members", { group: g.name, status: "Banned" }).then(function (rows) {
      $("ga-banned").innerHTML = rows.length ? rows.map(function (m) {
        return memberRow(m, '<button class="es-btn" data-a="unban">Unban</button>');
      }).join("") : '<span class="es-muted">Nobody is banned.</span>';
      $("ga-banned").querySelectorAll("[data-a]").forEach(function (b) {
        b.onclick = function () { ES.call("group_admin.unban_member", { group: g.name, user: b.closest(".es-member").dataset.user }).then(reload); };
      });
    });

    function loadInvites() {
      ES.call("group_admin.list_invites", { group: g.name }).then(function (rows) {
        $("ga-invites").innerHTML = rows.length ? rows.map(function (r) {
          var url = location.origin + "/social/group/" + g.name + "?invite=" + r.token;
          return '<div class="es-invite"><input class="es-input" readonly value="' + esc(url) + '">' +
            '<span class="es-muted">' + (r.use_count || 0) + (r.max_uses ? "/" + r.max_uses : "") + " used" +
            (r.expires_on ? " · expires " + esc(fmtDT(r.expires_on, { day: "numeric", month: "short" })) : "") + "</span>" +
            '<button class="es-btn" data-n="' + esc(r.name) + '">Revoke</button></div>';
        }).join("") : '<span class="es-muted">No active links.</span>';
        $("ga-invites").querySelectorAll("input").forEach(function (i) { i.onclick = function () { i.select(); }; });
        $("ga-invites").querySelectorAll("[data-n]").forEach(function (b) {
          b.onclick = function () { ES.call("group_admin.revoke_invite", { name: b.dataset.n }).then(loadInvites); };
        });
      });
    }
    loadInvites();
    $("ga-newinv").onclick = function () {
      var days = prompt("Link valid for how many days? (0 = no expiry)", "7"); if (days === null) return;
      var uses = prompt("Maximum uses? (0 = unlimited)", "0"); if (uses === null) return;
      ES.call("group_admin.create_invite", { group: g.name, days: days, max_uses: uses }).then(loadInvites);
    };

    var st = $("ga-settings");
    if (st) {
      st.innerHTML =
        '<label class="es-label">Description</label><textarea class="es-input" id="gs-desc" rows="3">' + esc(g.description || "") + "</textarea>" +
        '<label class="es-label">Rules</label><textarea class="es-input" id="gs-rules" rows="4">' + esc(g.rules || "") + "</textarea>" +
        '<div class="es-row2"><div><label class="es-label">Privacy</label><select class="es-input" id="gs-privacy">' +
        ["Public", "Closed", "Secret"].map(function (p) { return "<option" + (p === g.privacy ? " selected" : "") + ">" + p + "</option>"; }).join("") + "</select></div>" +
        '<div><label class="es-label">Joining</label><select class="es-input" id="gs-join">' +
        ["Open", "Approval Required"].map(function (p) { return "<option" + (p === g.join_policy ? " selected" : "") + ">" + p + "</option>"; }).join("") + "</select></div></div>" +
        '<label class="es-check"><input type="checkbox" id="gs-approval"' + (g.post_approval ? " checked" : "") + "> Posts need admin approval</label>" +
        '<div class="es-modal-actions"><button class="es-btn" id="gs-cover">Change cover</button><button class="es-btn es-btn-primary" id="gs-save">Save settings</button></div>';
      var save = function (confirmWiden) {
        ES.call("group_admin.update_group", {
          group: g.name, description: $("gs-desc").value, rules: $("gs-rules").value,
          privacy: $("gs-privacy").value, join_policy: $("gs-join").value,
          post_approval: $("gs-approval").checked ? 1 : 0, confirm_widen: confirmWiden ? 1 : 0
        }).then(function (r) {
          if (r && r.needs_confirmation) { if (confirm(r.message + "\n\nContinue?")) save(true); return; }
          alert("Saved."); location.reload();
        }).catch(function (e) { fail(e); });
      };
      $("gs-save").onclick = function () { save(false); };
      $("gs-cover").onclick = function () {
        var input = document.createElement("input"); input.type = "file"; input.accept = "image/*";
        input.onchange = function () {
          var f = input.files && input.files[0]; if (!f) return;
          ES.uploadFile(f).then(function (url) {
            if (url) return ES.call("group_admin.update_group", { group: g.name, cover_image: url }).then(function () { location.reload(); });
          }).catch(function (e) { fail(e); });
        };
        input.click();
      };
    }
  }

  // ---- album owner tools: drag to reorder, set cover ----------------------------
  ES.hooks.albumOwner = function (a) {
    var grid = $("es-album-grid");
    if (!grid || !(a.photos || []).length) return;
    var head = $("es-album-head");
    if (head) head.insertAdjacentHTML("beforeend", '<div class="es-muted es-hint">Tip: drag photos to reorder them · ★ sets the album cover</div>');
    grid.querySelectorAll(".es-photo-cell").forEach(function (cell) {
      var p = a.photos[parseInt(cell.dataset.i, 10)];
      cell.dataset.name = p.name;
      cell.draggable = true;
      cell.insertAdjacentHTML("beforeend", '<button class="es-photo-cover" title="Set as cover">★</button>');
      cell.querySelector(".es-photo-cover").onclick = function (e) {
        e.stopPropagation();
        ES.call("albums.set_cover", { album: a.name, photo: p.name }).then(function (r) {
          var cv = head && head.querySelector(".es-cover");
          if (cv && r.cover_image) cv.style.backgroundImage = "url(" + r.cover_image + ")";
        });
      };
    });
    var dragging = null;
    grid.addEventListener("dragstart", function (e) { dragging = e.target.closest(".es-photo-cell"); if (dragging) dragging.classList.add("es-dragging"); });
    grid.addEventListener("dragend", function () { if (dragging) dragging.classList.remove("es-dragging"); dragging = null; });
    grid.addEventListener("dragover", function (e) {
      e.preventDefault();
      var over = e.target.closest(".es-photo-cell");
      if (!dragging || !over || over === dragging) return;
      var r = over.getBoundingClientRect();
      over.parentNode.insertBefore(dragging, (e.clientX - r.left) > r.width / 2 ? over.nextSibling : over);
    });
    grid.addEventListener("drop", function (e) {
      e.preventDefault();
      var order = Array.prototype.map.call(grid.querySelectorAll(".es-photo-cell"), function (c) { return c.dataset.name; });
      ES.call("albums.reorder_photos", { album: a.name, order: order }).then(function () {
        // keep the lightbox order in step with the new grid order
        var byName = {}; (a.photos || []).forEach(function (p) { byName[p.name] = p; });
        ES._photos = order.map(function (n) { return byName[n]; });
        grid.querySelectorAll(".es-photo-cell").forEach(function (c, i) { c.dataset.i = i; });
      });
    });
  };

  // ---- messages page ---------------------------------------------------------------
  ES.pages.messages = function (root) {
    var convBox = $("es-dm-convs"), thread = $("es-dm-thread");
    var current = null, poll = null, lastSent = null;

    function loadConvs() {
      return ES.call("messages.list_conversations").then(function (rows) {
        convBox.innerHTML = rows.length ? rows.map(function (c) {
          return '<button class="es-dm-conv' + (c.unread ? " unread" : "") + (c.conversation === current ? " active" : "") +
            '" data-c="' + esc(c.conversation) + '">' + ES.avatar(c.profile_image, c.display_name, "es-avatar-sm") +
            '<div><b>' + esc(c.display_name) + '</b><div class="es-muted">' + (c.mine ? "You: " : "") + esc(c.last_message) + "</div></div></button>";
        }).join("") : '<div class="es-muted">No conversations yet. Start one from someone\'s profile.</div>';
      });
    }
    function bubble(m) {
      return '<div class="es-msg' + (m.mine ? " mine" : "") + '" data-name="' + esc(m.name) + '"><div>' + esc(m.content).replace(/\n/g, "<br>") +
        '</div><span class="es-msg-time">' + esc(fmtDT(m.sent_on, { hour: "numeric", minute: "2-digit", day: "numeric", month: "short" })) +
        (m.mine ? "" : ' · <a href="#" class="es-msg-report">Report</a>') + "</span></div>";
    }
    function openConv(id) {
      current = id;
      convBox.querySelectorAll(".es-dm-conv").forEach(function (b) { b.classList.toggle("active", b.dataset.c === id); });
      history.replaceState(null, "", "/social/messages?c=" + encodeURIComponent(id));
      ES.call("messages.get_messages", { conversation: id }).then(function (d) {
        var o = d.other;
        thread.innerHTML = '<div class="es-dm-head">' + ES.avatar(o.profile_image, o.display_name, "es-avatar-sm") +
          (o.profile_slug ? '<a href="/u/' + esc(o.profile_slug) + '">' + esc(o.display_name) + "</a>" : esc(o.display_name)) + "</div>" +
          '<div class="es-dm-msgs" id="es-dm-msgs">' + d.messages.map(bubble).join("") + "</div>" +
          (d.blocked ? '<div class="es-muted es-center">You can\'t message this member.</div>' :
            '<div class="es-dm-compose"><textarea id="es-dm-input" rows="1" placeholder="Write a message…"></textarea><button class="es-btn es-btn-primary" id="es-dm-send">Send</button></div>');
        var box = $("es-dm-msgs"); box.scrollTop = box.scrollHeight;
        lastSent = d.messages.length ? d.messages[d.messages.length - 1].sent_on : null;
        var input = $("es-dm-input"), send = $("es-dm-send");
        if (send) {
          var doSend = function () {
            var t = input.value.trim(); if (!t) return;
            send.disabled = true;
            ES.call("messages.send_message", { conversation: id, content: t }).then(function (m) {
              input.value = ""; send.disabled = false;
              box.insertAdjacentHTML("beforeend", bubble(m)); box.scrollTop = box.scrollHeight;
              lastSent = m.sent_on; loadConvs();
            }).catch(function (e) { send.disabled = false; fail(e); });
          };
          send.onclick = doSend;
          input.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSend(); } });
          input.focus();
        }
        box.addEventListener("click", function (e) {
          var r = e.target.closest(".es-msg-report"); if (!r) return;
          e.preventDefault(); ES.openReport("Social Message", r.closest(".es-msg").dataset.name, "message");
        });
        loadConvs();
      }).catch(function () { thread.innerHTML = '<div class="es-muted es-center">Conversation not found.</div>'; });
    }
    function refreshThread() {
      if (!current || document.hidden) return;
      ES.call("messages.get_messages", { conversation: current }).then(function (d) {
        var box = $("es-dm-msgs"); if (!box) return;
        var fresh = d.messages.filter(function (m) { return !lastSent || m.sent_on > lastSent; });
        fresh.forEach(function (m) { if (!box.querySelector('[data-name="' + m.name + '"]')) box.insertAdjacentHTML("beforeend", bubble(m)); });
        if (fresh.length) { lastSent = fresh[fresh.length - 1].sent_on; box.scrollTop = box.scrollHeight; loadConvs(); }
      }).catch(function () {});
    }

    convBox.addEventListener("click", function (e) {
      var b = e.target.closest(".es-dm-conv"); if (b) openConv(b.dataset.c);
    });
    var qs = new URLSearchParams(location.search);
    loadConvs().then(function () {
      if (qs.get("c")) openConv(qs.get("c"));
      else if (root.dataset.open) {
        ES.call("messages.start_conversation", { slug: root.dataset.open }).then(function (r) {
          if (r.provider === "Raven") location.href = r.url; else openConv(r.conversation);
        }).catch(function (e) { fail(e); });
      }
    });
    // live updates when Frappe realtime is available, polling otherwise
    if (window.frappe && frappe.realtime && frappe.realtime.on) {
      frappe.realtime.on("es_social_message", function (m) { if (m.conversation === current) refreshThread(); else loadConvs(); });
    }
    poll = setInterval(refreshThread, 8000);
    setInterval(function () { if (!document.hidden) loadConvs(); }, 30000);
  };

  // ---- pages directory -----------------------------------------------------------
  function pageCard(p) {
    return '<a class="es-group-card" href="/p/' + esc(p.slug) + '"><div class="es-group-cover"' +
      (p.avatar ? ' style="background-image:url(' + esc(p.avatar) + ')"' : "") + "></div>" +
      '<div class="es-group-name">' + esc(p.page_name) + (p.verified ? ' <span class="es-verified">✔</span>' : "") + "</div>" +
      '<div class="es-muted">' + esc(p.category || "") + (p.follower_count != null ? " · " + p.follower_count + " followers" : "") + "</div></a>";
  }
  ES.pages.pages = function () {
    var list = $("es-page-list"), mine = $("es-my-pages");
    function load(q) {
      ES.call("pages.list_pages", { query: q || "" }).then(function (rows) {
        list.innerHTML = rows.length ? rows.map(pageCard).join("") : '<div class="es-muted">No pages found.</div>';
      });
    }
    load();
    var t; $("es-page-search").addEventListener("input", function (e) { clearTimeout(t); t = setTimeout(function () { load(e.target.value); }, 300); });
    if (!ES.isGuest) ES.call("pages.my_pages").then(function (rows) {
      if (rows.length) mine.innerHTML = '<div class="es-card-title es-sub">Pages you manage</div>' + rows.map(pageCard).join("");
    });
    var nb = $("es-new-page");
    if (nb) nb.onclick = function () {
      var md = ES.modal("Create a page",
        '<label class="es-label">Page name</label><input class="es-input" id="pg-name" maxlength="120">' +
        '<label class="es-label">Category</label><select class="es-input" id="pg-cat">' +
        ["Business", "Brand", "Club", "Community", "Organisation", "Event Series", "Other"].map(function (c) { return "<option>" + c + "</option>"; }).join("") + "</select>" +
        '<label class="es-label">About</label><textarea class="es-input" id="pg-about" rows="3"></textarea>' +
        '<div class="es-row2"><div><label class="es-label">Website</label><input class="es-input" id="pg-web" placeholder="https://…"></div>' +
        '<div><label class="es-label">Location</label><input class="es-input" id="pg-loc"></div></div>' +
        '<div class="es-modal-actions"><button class="es-btn" data-close>Cancel</button><button class="es-btn es-btn-primary" id="pg-save">Create page</button></div>');
      md.el.querySelector("#pg-save").onclick = function () {
        var v = function (id) { return md.el.querySelector("#" + id).value.trim(); };
        if (!v("pg-name")) { alert("Give the page a name."); return; }
        ES.call("pages.create_page", { page_name: v("pg-name"), category: v("pg-cat"), about: v("pg-about"),
          website: v("pg-web"), location: v("pg-loc") }).then(function (r) { location.href = "/p/" + r.slug; })
          .catch(function (e) { fail(e); });
      };
    };
  };

  // ---- single page ---------------------------------------------------------------------
  ES.pages.page = function (root) {
    var slug = root.dataset.slug;
    ES.call("pages.get_page", { slug: slug }).then(function (pg) {
      var head = $("es-page-head");
      var followBtn = pg.is_admin ? '<button class="es-btn" id="pg-edit">Edit page</button>' :
        '<button class="es-btn' + (pg.following ? "" : " es-btn-primary") + '" id="pg-follow">' + (pg.following ? "✓ Following" : "+ Follow") + "</button>";
      head.innerHTML = '<div class="es-cover"' + (pg.cover_image ? ' style="background-image:url(' + esc(pg.cover_image) + ')"' : "") + "></div>" +
        '<div class="es-profile-id">' + ES.avatar(pg.avatar, pg.page_name, "es-avatar-xl") +
        "<div><h2>" + esc(pg.page_name) + (pg.verified ? ' <span class="es-verified" title="Verified by ES ERP">✔</span>' : "") + "</h2>" +
        '<div class="es-muted">' + esc(pg.category) + " · <span id=\"pg-followers\">" + (pg.follower_count || 0) + "</span> followers" +
        (pg.location ? " · " + esc(pg.location) : "") + "</div>" +
        (pg.website ? '<div><a href="' + esc(pg.website) + '" target="_blank" rel="noopener">' + esc(pg.website.replace(/^https?:\/\//, "")) + "</a></div>" : "") +
        '</div><div class="es-profile-actions">' + followBtn + ' <button class="es-btn" id="pg-more">⋯</button></div></div>' +
        (pg.about ? '<div class="es-profile-bio">' + pg.about + "</div>" : "") +
        (pg.products && pg.products.length ? '<div class="es-products">' + pg.products.map(function (p) {
          return '<a class="es-product" href="/' + esc(p.route || "") + '">' + (p.website_image ? '<img src="' + esc(p.website_image) + '">' : "") +
            "<span>" + esc(p.web_item_name) + "</span></a>";
        }).join("") + "</div>" : "");
      var fb = $("pg-follow");
      if (fb) fb.onclick = function () {
        if (ES.needsAccount("Sign up or log in to follow pages.")) return;
        ES.call("pages.follow", { page: pg.name, follow: pg.following ? 0 : 1 }).then(function (r) {
          pg.following = r.following;
          fb.textContent = r.following ? "✓ Following" : "+ Follow";
          fb.classList.toggle("es-btn-primary", !r.following);
          $("pg-followers").textContent = r.follower_count || 0;
        });
      };
      $("pg-more").onclick = function () {
        if (ES.needsAccount()) return;
        ES.menu($("pg-more"), [{ label: "Report page", action: function () { ES.openReport("Social Page", pg.name, "page"); } }]);
      };
      var ed = $("pg-edit");
      if (ed) ed.onclick = function () {
        var md = ES.modal("Edit page",
          '<label class="es-label">About</label><textarea class="es-input" id="pe-about" rows="4">' + esc(pg.about ? pg.about.replace(/<[^>]+>/g, "") : "") + "</textarea>" +
          '<div class="es-row2"><div><label class="es-label">Website</label><input class="es-input" id="pe-web" value="' + esc(pg.website || "") + '"></div>' +
          '<div><label class="es-label">Location</label><input class="es-input" id="pe-loc" value="' + esc(pg.location || "") + '"></div></div>' +
          '<div class="es-modal-actions"><button class="es-btn" id="pe-avatar">Change avatar</button><button class="es-btn" id="pe-cover">Change cover</button>' +
          '<button class="es-btn es-btn-primary" id="pe-save">Save</button></div>');
        var up = function (field) {
          var input = document.createElement("input"); input.type = "file"; input.accept = "image/*";
          input.onchange = function () {
            var f = input.files && input.files[0]; if (!f) return;
            ES.uploadFile(f).then(function (url) {
              var a = { page: pg.name }; a[field] = url;
              if (url) return ES.call("pages.update_page", a).then(function () { location.reload(); });
            });
          };
          input.click();
        };
        md.el.querySelector("#pe-avatar").onclick = function () { up("avatar"); };
        md.el.querySelector("#pe-cover").onclick = function () { up("cover_image"); };
        md.el.querySelector("#pe-save").onclick = function () {
          ES.call("pages.update_page", { page: pg.name, about: md.el.querySelector("#pe-about").value,
            website: md.el.querySelector("#pe-web").value, location: md.el.querySelector("#pe-loc").value })
            .then(function () { location.reload(); }).catch(function (e) { fail(e); });
        };
      };
      if (pg.is_admin) {
        var comp = $("es-page-composer"); comp.style.display = "";
        if (ES.flags.events) {
          var row = comp.querySelector(".es-composer-row");
          row.insertAdjacentHTML("afterbegin", '<button id="es-event-btn" class="es-btn" type="button">📅 Event</button>');
        }
        ES.wireComposer({ page: pg.name });
      }
      if (ES.flags.events) {
        $("es-page-events").innerHTML = '<div class="es-card" id="pg-upc" hidden><div class="es-card-title">📅 Upcoming events</div><div id="pg-upc-body"></div></div>';
        loadUpcoming({ page: pg.name }, $("pg-upc"), $("pg-upc-body"));
      }
      ES.state.mode = "page"; ES.state.arg = slug;
      ES.loadFeed(); ES.wireScroll();
    }).catch(function () { $("es-page-head").innerHTML = '<div class="es-muted es-center">Page not found.</div>'; });
  };

  // ---- settings page -----------------------------------------------------------------
  ES.pages.settings = function () {
    ES.call("notification_prefs.get_settings").then(function (s) {
      var chk = function (f, label) { return '<label class="es-check"><input type="checkbox" data-f="' + f + '"' + (s[f] ? " checked" : "") + "> " + label + "</label>"; };
      $("es-prefs").innerHTML =
        '<label class="es-label">Send me a summary email</label><select class="es-input" data-f="digest_frequency">' +
        ["Daily", "Weekly", "Off"].map(function (o) { return "<option" + (o === s.digest_frequency ? " selected" : "") + ">" + o + "</option>"; }).join("") + "</select>" +
        '<div class="es-label">Include</div>' + chk("email_reactions", "Reactions") + chk("email_comments", "Comments & replies") +
        chk("email_friend_requests", "Friend requests") + chk("email_groups", "Group activity") + chk("email_events", "Event reminders") +
        (ES.flags.messaging ? chk("email_messages", "Unread messages") : "");
      $("es-privacy").innerHTML = ES.flags.messaging
        ? '<label class="es-label">Who can send you messages</label><select class="es-input" data-f="allow_messages_from">' +
          [["Connections", "Friends only"], ["Everyone", "Any member"], ["No one", "No one"]].map(function (o) {
            return '<option value="' + o[0] + '"' + (o[0] === s.allow_messages_from ? " selected" : "") + ">" + o[1] + "</option>";
          }).join("") + "</select>"
        : '<span class="es-muted">No privacy options for this site yet.</span>';
      document.querySelectorAll("[data-f]").forEach(function (el) {
        el.addEventListener("change", function () {
          var a = {}; a[el.dataset.f] = el.type === "checkbox" ? (el.checked ? 1 : 0) : el.value;
          ES.call("notification_prefs.save_settings", a).then(function () { flash(el); });
        });
      });
    });
    function loadBlocked() {
      ES.call("safety.list_blocked").then(function (rows) {
        $("es-blocked").innerHTML = rows.length ? rows.map(function (r) {
          return '<div class="es-member">' + ES.avatar(r.profile_image, r.display_name, "es-avatar-sm") +
            '<div class="es-member-name">' + esc(r.display_name) + '</div><button class="es-btn" data-s="' + esc(r.profile_slug) + '">Unblock</button></div>';
        }).join("") : '<span class="es-muted">You haven\'t blocked anyone.</span>';
        $("es-blocked").querySelectorAll("[data-s]").forEach(function (b) {
          b.onclick = function () { ES.call("safety.unblock_user", { slug: b.dataset.s }).then(loadBlocked); };
        });
      });
    }
    loadBlocked();
    function flash(el) { el.classList.add("es-saved"); setTimeout(function () { el.classList.remove("es-saved"); }, 900); }
  };

  // ---- moderation page --------------------------------------------------------------
  ES.pages.moderation = function () {
    ES.call("moderation.stats").then(function (s) {
      var box = $("es-mod-stats"); box.hidden = false;
      var tile = function (n, l) { return '<div class="es-stat"><b>' + n + "</b><span>" + l + "</span></div>"; };
      box.innerHTML = '<div class="es-stats">' + tile(s.open_items, "items reported") + tile(s.pending_posts, "pending posts") +
        tile(s.reports_7d, "reports (7 days)") + tile(s.suspended, "suspended") + tile(s.avg_resolve_hours + "h", "avg. resolve time") + "</div>" +
        '<div class="es-muted">Full charts: <a href="/app/dashboard-view/ES Social Moderation">ES Social Moderation dashboard</a> · ' +
        '<a href="/app/social-moderation-log">Moderation log</a></div>';
    }).catch(function () {});

    ES.call("moderation.pending_posts").then(function (posts) {
      var box = $("es-mod-pending");
      box.innerHTML = posts.length ? posts.map(function (p) {
        return '<div class="es-pending-item" data-post="' + esc(p.name) + '">' + ES.renderPost(p) +
          '<div class="es-modal-actions"><button class="es-btn" data-d="reject">Reject</button><button class="es-btn es-btn-primary" data-d="approve">Approve</button></div></div>';
      }).join("") : '<span class="es-muted">Nothing waiting.</span>';
      box.querySelectorAll("[data-d]").forEach(function (b) {
        b.onclick = function () {
          var it = b.closest(".es-pending-item");
          var notes = b.dataset.d === "reject" ? (prompt("Reason (sent to the author, optional):") || "") : "";
          ES.call("moderation.review_post", { post: it.dataset.post, decision: b.dataset.d, notes: notes }).then(function () { it.remove(); });
        };
      });
    });

    var statusSel = $("es-mod-status");
    function loadQueue() {
      var open = statusSel.value === "Open";
      ES.call("moderation.get_queue", { status: statusSel.value }).then(function (items) {
        var box = $("es-mod-queue");
        box.innerHTML = items.length ? items.map(function (it) {
          var pv = it.preview || {};
          var reasons = Object.keys(it.reasons).map(function (k) { return esc(k) + (it.reasons[k] > 1 ? " ×" + it.reasons[k] : ""); }).join(", ");
          var who = it.reported_user_slug ? '<a href="/u/' + esc(it.reported_user_slug) + '">' + esc(it.reported_user_name) + "</a>" : esc(it.reported_user_name || "");
          var acts = open ? '<div class="es-mod-actions">' +
            (pv.hidden ? '<button class="es-btn" data-a="restore">Restore</button>' : (it.reference_doctype !== "User" && it.reference_doctype !== "Social Page" ? '<button class="es-btn" data-a="hide">Hide</button>' : "")) +
            '<button class="es-btn" data-a="dismiss">Dismiss</button><button class="es-btn" data-a="warn">Warn</button>' +
            (it.group ? '<button class="es-btn" data-a="ban_from_group">Ban from group</button>' : "") +
            (it.reported_user_suspended ? "" : '<button class="es-btn es-btn-danger" data-a="suspend">Suspend</button>') + "</div>" : "";
          return '<div class="es-mod-item" data-dt="' + esc(it.reference_doctype) + '" data-name="' + esc(it.reference_name) + '">' +
            '<div class="es-mod-meta"><b>' + esc(it.reference_doctype.replace("Social ", "")) + "</b> by " + who +
            ' · <span class="es-badge-pill">' + it.count + " report" + (it.count > 1 ? "s" : "") + "</span> · " + reasons +
            (pv.hidden ? ' · <span class="es-badge-pill es-badge-warn">hidden</span>' : "") +
            (it.reported_user_suspended ? ' · <span class="es-badge-pill es-badge-warn">suspended</span>' : "") + "</div>" +
            '<div class="es-mod-preview">' + esc(pv.text || "(no preview)") + (pv.url ? ' <a href="' + esc(pv.url) + '">open</a>' : "") + "</div>" +
            (it.details ? '<div class="es-muted">“' + it.details.map(esc).join("” · “") + "”</div>" : "") + acts + "</div>";
        }).join("") : '<span class="es-muted">No ' + statusSel.value.toLowerCase() + " reports.</span>";
        box.querySelectorAll("[data-a]").forEach(function (b) {
          b.onclick = function () {
            var it = b.closest(".es-mod-item"), a = b.dataset.a, args = { reference_doctype: it.dataset.dt, reference_name: it.dataset.name, action: a };
            if (a === "suspend") {
              var days = prompt("Suspend for how many days? (blank = until lifted)", "7"); if (days === null) return;
              args.days = days; args.notes = prompt("Reason (sent to the member):") || "";
            } else if (a === "warn" || a === "ban_from_group") {
              var n = prompt("Note (optional):"); if (n === null) return; args.notes = n;
            }
            ES.call("moderation.act", args).then(loadQueue).catch(function (e) { fail(e); });
          };
        });
      }).catch(function () { $("es-mod-queue").textContent = "Couldn't load the queue."; });
    }
    statusSel.onchange = loadQueue;
    loadQueue();
  };

  // ---- every page: unread message badge, feed extras ------------------------------------
  ES.hooks.afterBoot = function (page) {
    if (page === "feed") initFeedExtras();
    var badge = $("es-msg-badge");
    if (badge && !ES.isGuest && ES.flags.messaging) {
      var tick = function () {
        if (document.hidden) return;
        ES.call("messages.unread_count").then(function (n) { badge.hidden = !n; badge.textContent = n || ""; }).catch(function () {});
      };
      tick(); setInterval(tick, 60000);
    }
  };
})();
