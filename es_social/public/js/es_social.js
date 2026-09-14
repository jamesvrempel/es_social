/* ES Social — portal client
 * Copyright (c) 2026, Enterprise Systems Australia and contributors
 * Talks to whitelisted es_social.api.* methods via frappe.call.
 */
(function () {
  "use strict";

  if (window.ES_CFG && window.ES_CFG.csrf && window.frappe) {
    frappe.csrf_token = window.ES_CFG.csrf;
  }

  var ES = {
    state: { start: 0, pageLength: 15, loading: false, done: false, mode: null, arg: null },
    reactions: { Like: "👍", Love: "❤️", Care: "🥰", Haha: "😆", Wow: "😮", Sad: "😢", Angry: "😡" },

    call: function (method, args) {
      return new Promise(function (resolve, reject) {
        frappe.call({
          method: "es_social.api." + method,
          args: args || {},
          callback: function (r) { resolve(r.message); },
          error: function (e) { reject(e); },
        });
      });
    },

    esc: function (s) {
      var d = document.createElement("div");
      d.textContent = s == null ? "" : String(s);
      return d.innerHTML;
    },

    timeAgo: function (iso) {
      if (!iso) return "";
      var t = new Date(iso.replace(" ", "T"));
      var s = Math.floor((Date.now() - t.getTime()) / 1000);
      if (isNaN(s)) return "";
      if (s < 60) return "just now";
      if (s < 3600) return Math.floor(s / 60) + "m";
      if (s < 86400) return Math.floor(s / 3600) + "h";
      if (s < 604800) return Math.floor(s / 86400) + "d";
      return t.toLocaleDateString();
    },

    avatar: function (src, name, cls) {
      cls = cls || "es-avatar";
      if (src) return '<img class="' + cls + '" src="' + ES.esc(src) + '">';
      var initials = (name || "?").trim().slice(0, 1).toUpperCase();
      return '<span class="' + cls + ' es-avatar-fallback">' + ES.esc(initials) + "</span>";
    },

    maxUploadMB: 5,

    // Upload one File object to Frappe's standard endpoint; resolves with file_url.
    uploadFile: function (file, isPrivate) {
      return new Promise(function (resolve, reject) {
        if (file.size > ES.maxUploadMB * 1024 * 1024) {
          reject(new Error("File is larger than " + ES.maxUploadMB + " MB."));
          return;
        }
        var token = (window.frappe && frappe.csrf_token) ||
                    (window.ES_CFG && ES_CFG.csrf) || "";
        var fd = new FormData();
        fd.append("file", file, file.name);
        fd.append("is_private", isPrivate ? 1 : 0);
        fd.append("folder", "Home/Attachments");
        fd.append("optimize", 1);
        fetch("/api/method/upload_file", {
          method: "POST",
          headers: { "X-Frappe-CSRF-Token": token },
          body: fd,
          credentials: "same-origin",
        }).then(function (res) {
          if (!res.ok) { reject(new Error("Upload failed (" + res.status + ")")); return null; }
          return res.json();
        }).then(function (data) {
          resolve(data && data.message ? data.message.file_url : null);
        }).catch(reject);
      });
    },

    // Client mirror of the server allowlist — for composer preview only.
    videoEmbed: function (url) {
      if (!url) return null;
      var m = url.match(/(?:youtube\.com\/(?:watch\?v=|embed\/|shorts\/|v\/)|youtu\.be\/)([A-Za-z0-9_-]{6,})/);
      if (m) return "https://www.youtube.com/embed/" + m[1];
      m = url.match(/vimeo\.com\/(?:video\/)?(\d+)/);
      if (m) return "https://player.vimeo.com/video/" + m[1];
      return null;
    },
  };
  window.ES = ES;

  // ---- post rendering ------------------------------------------------------
  function renderComment(c) {
    return (
      '<div class="es-comment">' +
      ES.avatar(c.author_image, c.author_name, "es-avatar-sm") +
      '<div class="es-comment-body"><b>' + ES.esc(c.author_name) + "</b> " +
      ES.esc(c.content) +
      '<div class="es-comment-meta">' + ES.timeAgo(c.posted_on) + "</div></div></div>"
    );
  }

  function renderPost(p) {
    var mediaHtml = "";
    if (p.media && p.media.length) {
      mediaHtml = '<div class="es-media es-media-' + Math.min(p.media.length, 4) + '">';
      p.media.forEach(function (m) {
        mediaHtml += '<img src="' + ES.esc(m.image) + '">';
      });
      mediaHtml += "</div>";
    }

    var sharedHtml = "";
    if (p.shared) {
      sharedHtml =
        '<div class="es-shared">' +
        '<div class="es-post-head"><b>' + ES.esc(p.shared.author_name) + "</b>" +
        '<span class="es-muted">· ' + ES.timeAgo(p.shared.posted_on) + "</span></div>" +
        '<div class="es-post-content">' + (p.shared.content || "") + "</div></div>";
    }

    var linkHtml = "";
    if (p.link_url) {
      linkHtml =
        '<a class="es-linkcard" href="' + ES.esc(p.link_url) + '" target="_blank" rel="noopener">' +
        (p.link_image ? '<img src="' + ES.esc(p.link_image) + '">' : "") +
        '<div class="es-linkcard-t">' + ES.esc(p.link_title || p.link_url) + "</div></a>";
    }

    var videoHtml = "";
    if (p.video_embed) {
      videoHtml = '<div class="es-video"><iframe src="' + ES.esc(p.video_embed) +
        '" frameborder="0" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div>';
    }

    var myReaction = p.my_reaction;
    var reactBtnLabel = myReaction ? (ES.reactions[myReaction] + " " + myReaction) : "👍 Like";

    var comments = (p.top_comments || []).map(renderComment).join("");

    var authorLink = p.author_slug ? ("/u/" + ES.esc(p.author_slug)) : "#";

    return (
      '<article class="es-card es-post" data-name="' + ES.esc(p.name) + '">' +
      '<div class="es-post-head">' +
      ES.avatar(p.author_image, p.author_name) +
      '<div><a class="es-post-author" href="' + authorLink + '">' + ES.esc(p.author_name) + "</a>" +
      '<div class="es-post-meta">' + ES.timeAgo(p.posted_on) + " · " + ES.esc(p.visibility) + "</div></div>" +
      (p.can_edit ? '<button class="es-del es-icon-btn" title="Delete">✕</button>' : "") +
      "</div>" +
      '<div class="es-post-content">' + (p.content || "") + "</div>" +
      mediaHtml + videoHtml + linkHtml + sharedHtml +
      '<div class="es-post-counts"><span class="es-like-count">' + (p.like_count || 0) +
      "</span> reactions · <span class=\"es-comment-count\">" + (p.comment_count || 0) + "</span> comments</div>" +
      '<div class="es-post-actions">' +
      '<button class="es-react es-action' + (myReaction ? " es-reacted" : "") + '">' + reactBtnLabel + "</button>" +
      '<div class="es-react-tray">' +
      Object.keys(ES.reactions).map(function (k) {
        return '<button data-r="' + k + '" title="' + k + '">' + ES.reactions[k] + "</button>";
      }).join("") + "</div>" +
      '<button class="es-comment-toggle es-action">💬 Comment</button>' +
      '<button class="es-share es-action">↪ Share</button>' +
      "</div>" +
      '<div class="es-comments">' + comments +
      '<div class="es-comment-form"><input type="text" class="es-comment-input" placeholder="Write a comment…">' +
      '<button class="es-comment-send es-btn">Send</button></div></div>' +
      "</article>"
    );
  }

  // ---- feed loading --------------------------------------------------------
  function loadFeed() {
    if (ES.state.loading || ES.state.done) return;
    ES.state.loading = true;
    var sentinel = document.getElementById("es-feed-sentinel");
    if (sentinel) sentinel.textContent = "Loading…";

    var method = "feed.get_feed", args = { start: ES.state.start, page_length: ES.state.pageLength };
    if (ES.state.mode === "profile") { method = "feed.get_profile_feed"; args.user = ES.state.arg; }
    if (ES.state.mode === "group") { method = "feed.get_group_feed"; args.group = ES.state.arg; }

    ES.call(method, args).then(function (posts) {
      var feed = document.getElementById("es-feed");
      (posts || []).forEach(function (p) {
        feed.insertAdjacentHTML("beforeend", renderPost(p));
      });
      ES.state.start += (posts || []).length;
      ES.state.loading = false;
      if (!posts || posts.length < ES.state.pageLength) {
        ES.state.done = true;
        if (sentinel) sentinel.textContent = posts && posts.length ? "You're all caught up." : "Nothing here yet.";
      } else if (sentinel) { sentinel.textContent = ""; }
    }).catch(function () {
      ES.state.loading = false;
      if (sentinel) sentinel.textContent = "Couldn't load the feed.";
    });
  }

  // ---- delegated events ----------------------------------------------------
  function wireFeedEvents() {
    var root = document.querySelector(".es-social");
    if (!root) return;

    root.addEventListener("click", function (e) {
      var post = e.target.closest(".es-post");

      // reaction tray toggle
      if (e.target.closest(".es-react")) {
        var tray = post.querySelector(".es-react-tray");
        var already = post.querySelector(".es-react").classList.contains("es-reacted");
        if (already) {
          ES.call("posts.unreact", { reference_name: post.dataset.name }).then(function (r) {
            updateReaction(post, r);
          });
        } else {
          tray.classList.toggle("open");
        }
        return;
      }
      if (e.target.closest(".es-react-tray [data-r]")) {
        var rtype = e.target.closest("[data-r]").dataset.r;
        ES.call("posts.react", { reference_name: post.dataset.name, reaction_type: rtype })
          .then(function (r) { updateReaction(post, r); post.querySelector(".es-react-tray").classList.remove("open"); });
        return;
      }
      // comment toggle
      if (e.target.closest(".es-comment-toggle")) {
        post.querySelector(".es-comments").classList.toggle("open");
        var inp = post.querySelector(".es-comment-input"); if (inp) inp.focus();
        return;
      }
      // send comment
      if (e.target.closest(".es-comment-send")) {
        sendComment(post); return;
      }
      // share
      if (e.target.closest(".es-share")) {
        var txt = prompt("Say something about this (optional):", "");
        if (txt === null) return;
        ES.call("posts.share_post", { shared_post: post.dataset.name, content: txt })
          .then(function () { alert("Shared to your timeline."); });
        return;
      }
      // delete
      if (e.target.closest(".es-del")) {
        if (!confirm("Delete this post?")) return;
        ES.call("posts.delete_post", { name: post.dataset.name })
          .then(function () { post.remove(); });
        return;
      }
    });

    root.addEventListener("keydown", function (e) {
      if (e.target.classList.contains("es-comment-input") && e.key === "Enter") {
        sendComment(e.target.closest(".es-post"));
      }
    });
  }

  function updateReaction(post, r) {
    post.querySelector(".es-like-count").textContent = r.like_count || 0;
    var btn = post.querySelector(".es-react");
    if (r.my_reaction) {
      btn.classList.add("es-reacted");
      btn.textContent = ES.reactions[r.my_reaction] + " " + r.my_reaction;
    } else {
      btn.classList.remove("es-reacted");
      btn.textContent = "👍 Like";
    }
  }

  function sendComment(post) {
    var input = post.querySelector(".es-comment-input");
    var text = (input.value || "").trim();
    if (!text) return;
    input.value = "";
    ES.call("comments.add_comment", { reference_post: post.dataset.name, content: text })
      .then(function (c) {
        input.insertAdjacentHTML("beforebegin", renderComment(c));
        var cc = post.querySelector(".es-comment-count");
        cc.textContent = (parseInt(cc.textContent || "0", 10) + 1);
      });
  }

  // ---- composer ------------------------------------------------------------
  function wireComposer(extraArgs) {
    var btn = document.getElementById("es-post-btn");
    if (!btn) return;
    var composer = btn.closest(".es-composer");
    var media = [];

    // Build photo controls once, injected so both feed & group composers get them.
    var fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = "image/*";
    fileInput.multiple = true;
    fileInput.style.display = "none";

    var previews = document.createElement("div");
    previews.className = "es-composer-previews";

    var photoBtn = document.createElement("button");
    photoBtn.type = "button";
    photoBtn.className = "es-btn es-photo-btn";
    photoBtn.innerHTML = "\uD83D\uDCF7 Photo";

    var videoBtn = document.createElement("button");
    videoBtn.type = "button";
    videoBtn.className = "es-btn es-video-btn";
    videoBtn.innerHTML = "\uD83C\uDFAC Video";
    var videoUrl = null;

    var row = btn.parentNode;
    row.insertBefore(videoBtn, row.firstChild);
    row.insertBefore(photoBtn, row.firstChild);
    if (composer) {
      composer.insertBefore(previews, row);
      composer.appendChild(fileInput);
    }

    function renderPreviews() {
      var html = media.map(function (m, i) {
        return '<div class="es-prev"><img src="' + ES.esc(m.image) + '">' +
          '<button type="button" class="es-prev-x" data-i="' + i + '">\u2715</button></div>';
      }).join("");
      if (videoUrl) {
        var emb = ES.videoEmbed(videoUrl);
        html += '<div class="es-prev es-prev-video">' +
          (emb ? '<iframe src="' + ES.esc(emb) + '" frameborder="0" allowfullscreen></iframe>' : '<span>\uD83C\uDFAC</span>') +
          '<button type="button" class="es-prev-x" data-vid="1">\u2715</button></div>';
      }
      previews.innerHTML = html;
      previews.querySelectorAll(".es-prev-x").forEach(function (x) {
        x.onclick = function () {
          if (x.dataset.vid) { videoUrl = null; }
          else { media.splice(parseInt(x.dataset.i, 10), 1); }
          renderPreviews();
        };
      });
    }

    videoBtn.onclick = function () {
      var url = prompt("Paste a YouTube or Vimeo link:", videoUrl || "");
      if (url === null) return;
      url = url.trim();
      if (!url) { videoUrl = null; renderPreviews(); return; }
      if (!ES.videoEmbed(url)) {
        alert("That link isn't supported yet — use a YouTube or Vimeo URL.");
        return;
      }
      videoUrl = url;
      media = [];          // video and photos are mutually exclusive per post
      renderPreviews();
    };

    var pending = 0;
    function setBusy(b) {
      if (b) { pending += 1; } else { pending = Math.max(0, pending - 1); }
      photoBtn.disabled = pending > 0;
      photoBtn.innerHTML = pending > 0 ? "Uploading\u2026" : "\uD83D\uDCF7 Photo";
    }

    photoBtn.onclick = function () { fileInput.click(); };
    fileInput.onchange = function () {
      var files = Array.prototype.slice.call(fileInput.files || []);
      fileInput.value = "";
      if (files.length) videoUrl = null;   // photos replace a video attachment
      files.forEach(function (f) {
        setBusy(true);
        ES.uploadFile(f).then(function (url) {
          if (url) { media.push({ image: url }); renderPreviews(); }
          setBusy(false);
        }).catch(function (e) {
          setBusy(false);
          alert((e && e.message) || "Upload failed.");
        });
      });
    };

    btn.addEventListener("click", function () {
      var ta = document.getElementById("es-composer-text");
      var vis = document.getElementById("es-composer-visibility");
      var content = (ta.value || "").trim();
      if (!content && !media.length && !videoUrl) return;
      if (pending > 0) { alert("Please wait for photos to finish uploading."); return; }
      var args = { content: content };
      if (vis) args.visibility = vis.value;
      if (videoUrl) args.video_url = videoUrl;
      else if (media.length) args.media = media;
      Object.assign(args, extraArgs || {});
      btn.disabled = true;
      ES.call("posts.create_post", args).then(function (p) {
        var feed = document.getElementById("es-feed");
        feed.insertAdjacentHTML("afterbegin", renderPost(p));
        ta.value = ""; media = []; videoUrl = null; renderPreviews(); btn.disabled = false;
      }).catch(function () { btn.disabled = false; alert("Couldn't post."); });
    });
  }

  // ---- requests / search widgets (home) -----------------------------------
  function loadRequests() {
    var box = document.getElementById("es-requests-body");
    if (!box) return;
    ES.call("connections.pending_requests").then(function (rows) {
      if (!rows || !rows.length) { box.innerHTML = '<span class="es-muted">No pending requests.</span>'; return; }
      box.innerHTML = rows.map(function (r) {
        return '<div class="es-req" data-name="' + ES.esc(r.name) + '">' +
          ES.avatar(r.profile_image, r.display_name, "es-avatar-sm") +
          "<span>" + ES.esc(r.display_name) + "</span>" +
          '<button class="es-btn es-btn-primary es-req-accept">Accept</button>' +
          '<button class="es-btn es-req-decline">✕</button></div>';
      }).join("");
      box.querySelectorAll(".es-req").forEach(function (el) {
        el.querySelector(".es-req-accept").onclick = function () {
          ES.call("connections.respond_request", { name: el.dataset.name, action: "accept" }).then(function () { el.remove(); });
        };
        el.querySelector(".es-req-decline").onclick = function () {
          ES.call("connections.respond_request", { name: el.dataset.name, action: "decline" }).then(function () { el.remove(); });
        };
      });
    });
  }

  function wireSearch() {
    var inp = document.getElementById("es-search");
    var out = document.getElementById("es-search-results");
    if (!inp) return;
    var t;
    inp.addEventListener("input", function () {
      clearTimeout(t);
      var q = inp.value.trim();
      if (q.length < 2) { out.innerHTML = ""; return; }
      t = setTimeout(function () {
        ES.call("profile.search_people", { query: q }).then(function (rows) {
          out.innerHTML = (rows || []).map(function (r) {
            return '<a class="es-search-item" href="/u/' + ES.esc(r.profile_slug) + '">' +
              ES.avatar(r.profile_image, r.display_name, "es-avatar-sm") +
              "<span>" + ES.esc(r.display_name) + "</span></a>";
          }).join("") || '<div class="es-muted es-pad">No matches</div>';
        });
      }, 250);
    });
    document.addEventListener("click", function (e) { if (!inp.contains(e.target)) out.innerHTML = ""; });
  }

  // ---- profile page --------------------------------------------------------
  function initProfile(slug) {
    ES.call("profile.get_profile", { slug: slug }).then(function (pf) {
      var head = document.getElementById("es-profile-head");
      var cover = pf.cover_image ? ('<div class="es-cover" style="background-image:url(' + pf.cover_image + ')"></div>') : '<div class="es-cover"></div>';
      var btn = "";
      if (pf.is_self) {
        btn = '<button class="es-btn" id="es-avatar-btn">\uD83D\uDCF7 Photo</button> ' +
              '<a class="es-btn" href="/app/social-profile/' + encodeURIComponent(pf.user) + '">Edit profile</a>';
      } else if (pf.connection) {
        var st = pf.connection.status;
        if (st === "accepted") btn = '<button class="es-btn" id="es-conn-btn" data-act="unfriend">✓ Friends</button>';
        else if (st === "outgoing") btn = '<button class="es-btn" disabled>Request sent</button>';
        else if (st === "incoming") btn = '<button class="es-btn es-btn-primary" id="es-conn-btn" data-act="accept" data-name="' + ES.esc(pf.connection.name) + '">Accept request</button>';
        else btn = '<button class="es-btn es-btn-primary" id="es-conn-btn" data-act="add">+ Add friend</button>';
      }
      var photosLink = '<a class="es-btn" href="/social/photos?u=' +
        encodeURIComponent(pf.profile_slug || "") + '">\uD83D\uDCF7 Photos</a>';
      head.innerHTML = cover +
        '<div class="es-profile-id">' + ES.avatar(pf.profile_image, pf.display_name, "es-avatar-xl") +
        "<div><h2>" + ES.esc(pf.display_name) + "</h2><div class=\"es-muted\">" + ES.esc(pf.headline || "") + "</div>" +
        '<div class="es-muted">' + (pf.connection_count || 0) + " friends · " + (pf.post_count || 0) + " posts</div></div>" +
        '<div class="es-profile-actions">' + btn + " " + photosLink + "</div></div>" +
        (pf.bio ? '<div class="es-profile-bio">' + pf.bio + "</div>" : "");

      var cb = document.getElementById("es-conn-btn");
      if (cb) cb.onclick = function () { handleConn(cb, pf.user); };

      if (pf.is_self) addProfilePhotoControls();

      ES.state.mode = "profile"; ES.state.arg = pf.user;
      loadFeed();
    });
  }

  // Avatar + cover upload controls, shown only on your own profile.
  function addProfilePhotoControls() {
    var head = document.getElementById("es-profile-head");
    if (!head) return;
    var coverEl = head.querySelector(".es-cover");

    // shared hidden input factory
    function pickAndUpload(after) {
      var input = document.createElement("input");
      input.type = "file"; input.accept = "image/*"; input.style.display = "none";
      head.appendChild(input);
      input.onchange = function () {
        var f = input.files && input.files[0];
        input.value = "";
        if (!f) return;
        after.busy(true);
        ES.uploadFile(f).then(function (url) {
          if (!url) { after.busy(false); return; }
          return ES.call("profile.update_profile", after.field(url)).then(function () {
            after.done(url); after.busy(false);
          });
        }).catch(function (e) { after.busy(false); alert((e && e.message) || "Upload failed."); });
      };
      input.click();
    }

    // cover
    if (coverEl) {
      var coverBtn = document.createElement("button");
      coverBtn.type = "button"; coverBtn.className = "es-cover-cam";
      coverBtn.innerHTML = "\uD83D\uDCF7 Cover";
      coverEl.appendChild(coverBtn);
      coverBtn.onclick = function () {
        pickAndUpload({
          busy: function (b) { coverBtn.disabled = b; coverBtn.innerHTML = b ? "\u2026" : "\uD83D\uDCF7 Cover"; },
          field: function (url) { return { cover_image: url }; },
          done: function (url) { coverEl.style.backgroundImage = "url(" + url + ")"; },
        });
      };
    }

    // avatar (button lives in the actions row)
    var avatarBtn = document.getElementById("es-avatar-btn");
    if (avatarBtn) {
      avatarBtn.onclick = function () {
        pickAndUpload({
          busy: function (b) { avatarBtn.disabled = b; avatarBtn.innerHTML = b ? "\u2026" : "\uD83D\uDCF7 Photo"; },
          field: function (url) { return { profile_image: url }; },
          done: function (url) {
            var el = head.querySelector(".es-avatar-xl");
            if (el && el.tagName === "IMG") { el.src = url; }
            else if (el) {
              var img = document.createElement("img");
              img.className = "es-avatar-xl"; img.src = url;
              el.parentNode.replaceChild(img, el);
            }
          },
        });
      };
    }
  }

  function handleConn(btn, user) {
    var act = btn.dataset.act;
    if (act === "add") ES.call("connections.send_request", { to_user: user }).then(function () { btn.textContent = "Request sent"; btn.disabled = true; });
    else if (act === "accept") ES.call("connections.respond_request", { name: btn.dataset.name, action: "accept" }).then(function () { btn.textContent = "✓ Friends"; btn.dataset.act = "unfriend"; });
    else if (act === "unfriend") { if (confirm("Remove friend?")) ES.call("connections.unfriend", { other_user: user }).then(function () { btn.textContent = "+ Add friend"; btn.dataset.act = "add"; }); }
  }

  // ---- groups pages --------------------------------------------------------
  function initGroups() {
    ES.call("groups.list_my_groups").then(function (rows) {
      document.getElementById("es-my-groups").innerHTML = (rows || []).map(groupCard).join("") ||
        '<span class="es-muted">You haven\'t joined any groups yet.</span>';
    });
    ES.call("groups.discover_groups").then(function (rows) {
      document.getElementById("es-discover-groups").innerHTML = (rows || []).map(function (g) {
        return groupCard(g, true);
      }).join("") || '<span class="es-muted">No groups to discover.</span>';
    });
    document.getElementById("es-discover-groups").addEventListener("click", function (e) {
      var j = e.target.closest(".es-join"); if (!j) return;
      ES.call("groups.join_group", { group: j.dataset.group }).then(function (r) {
        j.textContent = r.status === "Active" ? "Joined" : "Requested"; j.disabled = true;
      });
    });
  }

  function groupCard(g, discover) {
    return '<a class="es-group-card" href="/social/group/' + ES.esc(g.slug) + '">' +
      '<div class="es-group-cover" style="background-image:url(' + (g.cover_image || "") + ')"></div>' +
      '<div class="es-group-name">' + ES.esc(g.group_name) + "</div>" +
      '<div class="es-muted">' + (g.member_count || 0) + " members · " + ES.esc(g.privacy || "") + "</div>" +
      (discover ? '<button class="es-btn es-btn-primary es-join" data-group="' + ES.esc(g.name) + '">Join</button>' : "") +
      "</a>";
  }

  function initGroup(group) {
    ES.call("groups.get_group", { group: group }).then(function (g) {
      var head = document.getElementById("es-group-head");
      head.innerHTML =
        '<div class="es-cover" style="background-image:url(' + (g.cover_image || "") + ')"></div>' +
        '<div class="es-profile-id"><div><h2>' + ES.esc(g.group_name) + "</h2>" +
        '<div class="es-muted">' + (g.member_count || 0) + " members · " + ES.esc(g.privacy) + "</div></div>" +
        '<div class="es-profile-actions">' +
        (g.is_member ? '<button class="es-btn" id="es-leave">Leave</button>'
          : '<button class="es-btn es-btn-primary" id="es-join">Join group</button>') +
        "</div></div>" + (g.description ? '<div class="es-profile-bio">' + g.description + "</div>" : "");

      if (g.is_member) {
        var comp = document.getElementById("es-group-composer");
        if (comp) comp.style.display = "";
        wireComposer({ group: group, visibility: "Group" });
        var lv = document.getElementById("es-leave");
        if (lv) lv.onclick = function () { if (confirm("Leave group?")) ES.call("groups.leave_group", { group: group }).then(function () { location.reload(); }); };
      } else {
        var jn = document.getElementById("es-join");
        if (jn) jn.onclick = function () { ES.call("groups.join_group", { group: group }).then(function () { location.reload(); }); };
      }
      ES.state.mode = "group"; ES.state.arg = group;
      loadFeed();
    });
  }

  // ---- connections page ----------------------------------------------------
  function initConnections() {
    ES.call("connections.pending_requests").then(function (rows) {
      var box = document.getElementById("es-req-list");
      box.innerHTML = (rows || []).map(function (r) {
        return '<div class="es-req" data-name="' + ES.esc(r.name) + '">' +
          ES.avatar(r.profile_image, r.display_name, "es-avatar-sm") +
          "<span>" + ES.esc(r.display_name) + "</span>" +
          '<button class="es-btn es-btn-primary es-req-accept">Accept</button>' +
          '<button class="es-btn es-req-decline">Decline</button></div>';
      }).join("") || '<span class="es-muted">No pending requests.</span>';
      box.querySelectorAll(".es-req").forEach(function (el) {
        el.querySelector(".es-req-accept").onclick = function () { ES.call("connections.respond_request", { name: el.dataset.name, action: "accept" }).then(function () { el.remove(); }); };
        el.querySelector(".es-req-decline").onclick = function () { ES.call("connections.respond_request", { name: el.dataset.name, action: "decline" }).then(function () { el.remove(); }); };
      });
    });
    ES.call("connections.list_connections").then(function (rows) {
      document.getElementById("es-friend-list").innerHTML = (rows || []).map(function (r) {
        return '<a class="es-friend" href="/u/' + ES.esc(r.profile_slug) + '">' +
          ES.avatar(r.profile_image, r.display_name, "es-avatar-lg") +
          "<span>" + ES.esc(r.display_name) + "</span></a>";
      }).join("") || '<span class="es-muted">No friends yet — find people via search.</span>';
    });
  }

  // ---- photos gallery ------------------------------------------------------
  function initPhotos(slug) {
    loadAlbums(slug);
    var args = slug ? { slug: slug } : {};
    ES.call("photos.get_photos", args).then(function (res) {
      var grid = document.getElementById("es-photo-grid");
      var title = document.getElementById("es-photos-title");
      var empty = document.getElementById("es-photos-empty");
      var photos = (res && res.photos) || [];
      if (title) {
        title.textContent = res && res.is_self
          ? "Your photos"
          : ((res && res.display_name ? res.display_name : "") + " \u2014 Photos");
      }
      var up = document.getElementById("es-upload-photos");
      if (up && res && res.is_self) { up.style.display = ""; wireGalleryUpload(up); }
      if (!photos.length) {
        if (empty) empty.textContent = "No photos yet.";
        return;
      }
      ES._photos = photos;
      grid.innerHTML = photos.map(function (p, i) {
        return '<a class="es-photo-cell" data-i="' + i + '" href="' +
          (p.post ? "/social#" + ES.esc(p.post) : "#") + '"><img src="' + ES.esc(p.image) + '"></a>';
      }).join("");
      grid.querySelectorAll(".es-photo-cell").forEach(function (cell) {
        cell.onclick = function (e) { e.preventDefault(); openLightbox(parseInt(cell.dataset.i, 10)); };
      });
    }).catch(function () {
      var empty = document.getElementById("es-photos-empty");
      if (empty) empty.textContent = "Couldn't load photos.";
    });
  }

  function wireGalleryUpload(btn) {
    if (btn._wired) return;
    btn._wired = true;
    var input = document.createElement("input");
    input.type = "file"; input.accept = "image/*"; input.multiple = true; input.style.display = "none";
    document.body.appendChild(input);
    btn.onclick = function () { input.click(); };
    input.onchange = function () {
      var files = Array.prototype.slice.call(input.files || []);
      input.value = "";
      if (!files.length) return;
      btn.disabled = true; btn.textContent = "Uploading\u2026";
      var ups = files.map(function (f) {
        return ES.uploadFile(f).then(function (u) { return u ? { image: u } : null; })
          .catch(function (e) { alert((e && e.message) || "Upload failed."); return null; });
      });
      Promise.all(ups).then(function (media) {
        media = media.filter(function (m) { return m; });
        if (!media.length) { btn.disabled = false; btn.textContent = "\uFF0B Upload photos"; return; }
        ES.call("posts.create_post", { content: "", media: media, visibility: "Public" })
          .then(function () { location.reload(); })
          .catch(function () { btn.disabled = false; btn.textContent = "\uFF0B Upload photos"; alert("Couldn't upload."); });
      });
    };
  }

  function loadAlbums(slug) {
    var grid = document.getElementById("es-albums-grid");
    if (!grid) return;
    var args = slug ? { slug: slug } : {};
    ES.call("albums.list_albums", args).then(function (res) {
        var albums = (res && res.albums) || [];
        var empty = document.getElementById("es-albums-empty");
        var newBtn = document.getElementById("es-new-album");
        if (newBtn && res && res.is_self) {
          newBtn.style.display = "";
          newBtn.onclick = createAlbumPrompt;
        }
        if (!albums.length) {
          if (empty) empty.textContent = res && res.is_self
            ? "No albums yet — create one to get started."
            : "No albums to show.";
          grid.innerHTML = "";
          return;
        }
        if (empty) empty.textContent = "";
        grid.innerHTML = albums.map(function (a) {
          var cov = a.cover_image
            ? 'style="background-image:url(' + ES.esc(a.cover_image) + ')"'
            : "";
          return '<a class="es-album-card" href="/social/album/' + ES.esc(a.slug) + '">' +
            '<div class="es-album-cover" ' + cov + '></div>' +
            '<div class="es-album-name">' + ES.esc(a.title) + "</div>" +
            '<div class="es-muted">' + (a.photo_count || 0) + " photos · " + ES.esc(a.privacy) + "</div></a>";
        }).join("");
    });
  }

  function createAlbumPrompt() {
    var title = prompt("Album name:", "");
    if (!title) return;
    ES.call("albums.create_album", { title: title, privacy: "Public" }).then(function (a) {
      if (a && a.slug) window.location.href = "/social/album/" + a.slug;
    }).catch(function () { alert("Couldn't create album."); });
  }

  // ---- single album --------------------------------------------------------
  function initAlbum(slug) {
    ES.call("albums.get_album", { slug: slug }).then(function (a) {
      var head = document.getElementById("es-album-head");
      var owner = a.is_owner;
      var cov = a.cover_image ? 'style="background-image:url(' + ES.esc(a.cover_image) + ')"' : "";
      var ownerActions = owner
        ? '<div class="es-profile-actions">' +
            '<button class="es-btn es-btn-primary" id="es-add-photos">\uD83D\uDCF7 Add photos</button> ' +
            '<button class="es-btn" id="es-add-video">\uD83C\uDFAC Add video</button> ' +
            '<button class="es-btn" id="es-edit-album">Edit</button> ' +
            '<button class="es-btn" id="es-del-album">Delete</button></div>'
        : "";
      head.innerHTML =
        '<div class="es-cover" ' + cov + "></div>" +
        '<div class="es-profile-id"><div>' +
        "<h2>" + ES.esc(a.title) + "</h2>" +
        '<div class="es-muted">' + (a.photo_count || 0) + " photos · " + ES.esc(a.privacy) +
        (a.owner_slug ? ' · <a href="/u/' + ES.esc(a.owner_slug) + '">by owner</a>' : "") +
        "</div></div>" + ownerActions + "</div>" +
        (a.description ? '<div class="es-profile-bio">' + ES.esc(a.description) + "</div>" : "");

      renderAlbumPhotos(a);

      if (owner) {
        wireAddPhotos(a.name);
        var av = document.getElementById("es-add-video");
        if (av) av.onclick = function () {
          var url = prompt("Paste a YouTube or Vimeo link:", "");
          if (!url) return;
          if (!ES.videoEmbed(url)) { alert("Use a YouTube or Vimeo URL."); return; }
          ES.call("albums.add_video", { album: a.name, video_url: url })
            .then(function () { location.reload(); })
            .catch(function () { alert("Couldn't add video."); });
        };
        var del = document.getElementById("es-del-album");
        if (del) del.onclick = function () {
          if (confirm("Delete this album and all its photos?"))
            ES.call("albums.delete_album", { name: a.name }).then(function () {
              window.location.href = "/social/photos";
            });
        };
        var ed = document.getElementById("es-edit-album");
        if (ed) ed.onclick = function () {
          var t = prompt("Album name:", a.title);
          if (t === null) return;
          var pv = prompt("Privacy — Public, Connections, or Only Me:", a.privacy) || a.privacy;
          ES.call("albums.edit_album", { name: a.name, title: t, privacy: pv })
            .then(function () { location.reload(); });
        };
      }
    }).catch(function () {
      var head = document.getElementById("es-album-head");
      if (head) head.innerHTML = '<div class="es-muted es-center">Album not found or not visible.</div>';
    });
  }

  function renderAlbumPhotos(a) {
    var grid = document.getElementById("es-album-grid");
    var empty = document.getElementById("es-album-empty");
    var photos = a.photos || [];
    ES._photos = photos;
    if (!photos.length) {
      if (empty) empty.textContent = "No photos in this album yet.";
      grid.innerHTML = "";
      return;
    }
    if (empty) empty.textContent = "";
    grid.innerHTML = photos.map(function (p, i) {
      var del = a.is_owner
        ? '<button class="es-photo-del" data-name="' + ES.esc(p.name) + '" title="Delete">\u2715</button>'
        : "";
      var inner = p.video_embed
        ? '<div class="es-vidcell"><span class="es-play">\u25B6</span></div>'
        : '<img src="' + ES.esc(p.image) + '">';
      return '<div class="es-photo-cell" data-i="' + i + '">' + inner + del + "</div>";
    }).join("");
    grid.querySelectorAll(".es-photo-cell").forEach(function (cell) {
      cell.onclick = function (e) {
        if (e.target.closest(".es-photo-del")) return;
        openLightbox(parseInt(cell.dataset.i, 10));
      };
    });
    grid.querySelectorAll(".es-photo-del").forEach(function (b) {
      b.onclick = function (e) {
        e.stopPropagation();
        if (!confirm("Delete this photo?")) return;
        ES.call("albums.delete_photo", { name: b.dataset.name }).then(function () {
          location.reload();
        });
      };
    });
  }

  function wireAddPhotos(albumName) {
    var btn = document.getElementById("es-add-photos");
    if (!btn) return;
    var input = document.createElement("input");
    input.type = "file"; input.accept = "image/*"; input.multiple = true; input.style.display = "none";
    document.body.appendChild(input);
    btn.onclick = function () { input.click(); };
    input.onchange = function () {
      var files = Array.prototype.slice.call(input.files || []);
      input.value = "";
      if (!files.length) return;
      btn.disabled = true; btn.textContent = "Uploading\u2026";
      var uploads = files.map(function (f) {
        return ES.uploadFile(f).then(function (url) { return url ? { image: url } : null; })
          .catch(function () { return null; });
      });
      Promise.all(uploads).then(function (media) {
        media = media.filter(function (m) { return m; });
        if (!media.length) { btn.disabled = false; btn.innerHTML = "\uD83D\uDCF7 Add photos"; return; }
        ES.call("albums.add_photos", { album: albumName, media: media }).then(function () {
          location.reload();
        }).catch(function () {
          btn.disabled = false; btn.innerHTML = "\uD83D\uDCF7 Add photos"; alert("Couldn't add photos.");
        });
      });
    };
  }

  function openLightbox(startIndex) {
    var photos = ES._photos || [];
    if (!photos.length) return;
    var idx = startIndex;

    var overlay = document.createElement("div");
    overlay.className = "es-lightbox";

    function render() {
      var p = photos[idx];
      var stage = p.video_embed
        ? '<div class="es-lb-video"><iframe src="' + ES.esc(p.video_embed) +
          '" frameborder="0" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div>'
        : '<img src="' + ES.esc(p.image) + '">';
      overlay.innerHTML =
        '<button class="es-lb-close" title="Close">\u2715</button>' +
        '<button class="es-lb-prev" title="Previous">\u2039</button>' +
        '<div class="es-lb-stage">' + stage +
        (p.caption ? '<div class="es-lb-cap">' + ES.esc(p.caption) + "</div>" : "") +
        '<div class="es-lb-count">' + (idx + 1) + " / " + photos.length + "</div></div>" +
        '<button class="es-lb-next" title="Next">\u203A</button>';
      overlay.querySelector(".es-lb-close").onclick = close;
      overlay.querySelector(".es-lb-prev").onclick = function (e) { e.stopPropagation(); step(-1); };
      overlay.querySelector(".es-lb-next").onclick = function (e) { e.stopPropagation(); step(1); };
    }
    function step(d) { idx = (idx + d + photos.length) % photos.length; render(); }
    function close() {
      if (overlay.parentNode) document.body.removeChild(overlay);
      document.removeEventListener("keydown", key);
    }
    function key(e) {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "ArrowRight") step(1);
    }

    overlay.onclick = function (e) { if (e.target === overlay) close(); };
    document.addEventListener("keydown", key);
    render();
    document.body.appendChild(overlay);
  }

  // ---- infinite scroll -----------------------------------------------------
  function wireScroll() {
    var sentinel = document.getElementById("es-feed-sentinel");
    if (!sentinel || !("IntersectionObserver" in window)) return;
    new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting) loadFeed();
    }).observe(sentinel);
  }

  // ---- boot ----------------------------------------------------------------
  function boot() {
    var root = document.querySelector(".es-social");
    if (!root) return;
    var page = root.dataset.page;
    wireFeedEvents();
    ES.call("config.get_client_config").then(function (c) {
      if (c && c.max_upload_mb) ES.maxUploadMB = c.max_upload_mb;
    }).catch(function () {});

    if (page === "feed") {
      ES.state.mode = "home";
      wireComposer();
      wireSearch();
      loadRequests();
      loadFeed();
      wireScroll();
    } else if (page === "profile") {
      initProfile(root.dataset.slug);
      wireScroll();
    } else if (page === "groups") {
      initGroups();
    } else if (page === "photos") {
      initPhotos(root.dataset.slug);
    } else if (page === "album") {
      initAlbum(root.dataset.slug);
    } else if (page === "group") {
      initGroup(root.dataset.group);
      wireScroll();
    } else if (page === "connections") {
      initConnections();
    }
  }

  if (window.frappe && frappe.ready) frappe.ready(boot);
  else document.addEventListener("DOMContentLoaded", boot);
})();
