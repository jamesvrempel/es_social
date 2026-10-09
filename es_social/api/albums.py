# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Album + album-photo management."""

import json

import frappe
from frappe.utils import cint

from es_social.social.utils import GUEST, require_login, get_viewer, check_content, scrub_for_guest
from es_social.permissions.album import has_permission as _can_read_album

PRIVILEGED = {"System Manager", "Social Moderator", "Social Admin"}


def _load(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _is_privileged(user):
    return bool(PRIVILEGED & set(frappe.get_roles(user)))


def _owns(album_name, user):
    owner = frappe.db.get_value("Social Album", album_name, "owner_user")
    return owner == user or _is_privileged(user)


def _can_add(album_name, user):
    """Owners add to their albums; any active group member adds to a group album."""
    if _owns(album_name, user):
        return True
    group = frappe.db.get_value("Social Album", album_name, "group")
    if group:
        from es_social.social.utils import get_group_ids
        return group in get_group_ids(user)
    return False


@frappe.whitelist()
def create_album(title, description=None, privacy="Public", cover_image=None, group=None):
    viewer = require_login()
    check_content(title)
    if group:
        from es_social.social.utils import get_group_ids
        if group not in get_group_ids(viewer):
            frappe.throw(frappe._("Join the group to create an album in it."), frappe.PermissionError)
        # a group album is as visible as the group itself
        gp = frappe.db.get_value("Social Group", group, "privacy")
        privacy = "Public" if gp == "Public" else "Only Me"
    doc = frappe.new_doc("Social Album")
    doc.group = group
    doc.owner_user = viewer
    doc.title = title
    doc.description = description
    doc.privacy = privacy or "Public"
    doc.cover_image = cover_image
    doc.insert()
    frappe.db.commit()
    return doc.get_public_dict()


@frappe.whitelist()
def edit_album(name, title=None, description=None, privacy=None, cover_image=None):
    viewer = require_login()
    if not _owns(name, viewer):
        frappe.throw(frappe._("You can only edit your own albums."), frappe.PermissionError)
    doc = frappe.get_doc("Social Album", name)
    if title is not None:
        doc.title = title
    if description is not None:
        doc.description = description
    if privacy is not None:
        doc.privacy = privacy
    if cover_image is not None:
        doc.cover_image = cover_image
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return doc.get_public_dict()


@frappe.whitelist()
def delete_album(name):
    viewer = require_login()
    if not _owns(name, viewer):
        frappe.throw(frappe._("You can only delete your own albums."), frappe.PermissionError)
    for ph in frappe.get_all("Social Photo", filters={"album": name}, pluck="name"):
        frappe.delete_doc("Social Photo", ph, ignore_permissions=True, force=True)
    frappe.delete_doc("Social Album", name, ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist(allow_guest=True)
def list_albums(user=None, slug=None):
    """Albums of a user that the viewer may see (permission conditions applied).
    Guests see Public albums only and must identify the owner by profile slug."""
    viewer = get_viewer()
    if slug:
        user = frappe.db.get_value("Social Profile", {"profile_slug": slug}, "user")
    fields = ["name", "title", "slug", "privacy", "cover_image", "photo_count", "posted_on"]
    if viewer == GUEST:
        if not slug or not user:
            return {"albums": [], "user": None, "is_self": False}
        albums = frappe.get_all(
            "Social Album",
            filters={"owner_user": user, "privacy": "Public"},
            fields=fields,
            order_by="posted_on desc",
        )
        return {"albums": albums, "user": None, "is_self": False}
    user = user or viewer
    albums = frappe.get_list(
        "Social Album",
        filters={"owner_user": user},
        fields=fields,
        order_by="posted_on desc",
    )
    return {
        "albums": albums,
        "user": user,
        "is_self": user == viewer,
    }


@frappe.whitelist(allow_guest=True)
def get_album(album=None, slug=None, start=0, page_length=200):
    viewer = get_viewer()
    if slug and not album:
        album = frappe.db.get_value("Social Album", {"slug": slug}, "name")
    if not album or not frappe.db.exists("Social Album", album):
        frappe.throw(frappe._("Album not found."))

    doc = frappe.get_doc("Social Album", album)
    # direct check (works for Guest, who has no role DocPerms)
    if not _can_read_album(doc, "read", viewer):
        frappe.throw(frappe._("You can't view this album."), frappe.PermissionError)

    data = doc.get_public_dict()
    data["is_owner"] = viewer != GUEST and ((doc.owner_user == viewer) or _is_privileged(viewer))
    data["can_add"] = viewer != GUEST and _can_add(doc.name, viewer)
    data["group"] = doc.group
    owner_slug = frappe.db.get_value("Social Profile", {"user": doc.owner_user}, "profile_slug")
    data["owner_slug"] = owner_slug

    photos = frappe.get_all(
        "Social Photo",
        filters={"album": album},
        fields=["name", "image", "caption", "media_type", "video_url", "sort_order", "posted_on"],
        order_by="sort_order asc, posted_on asc",
        start=cint(start),
        page_length=cint(page_length) or 200,
    )
    from es_social.social.video import embed_for
    for p in photos:
        p["posted_on"] = str(p["posted_on"])
        if p.get("media_type") == "Video" and p.get("video_url"):
            p["video_embed"] = embed_for(p["video_url"])
    data["photos"] = photos
    return scrub_for_guest(data, viewer)


@frappe.whitelist()
def add_photos(album, media):
    """media: list of {image, caption} (or bare url strings)."""
    viewer = require_login()
    if not _can_add(album, viewer):
        frappe.throw(frappe._("You can't add photos to this album."), frappe.PermissionError)
    media = _load(media) or []
    created = []
    base = frappe.db.count("Social Photo", {"album": album})
    for i, m in enumerate(media):
        img = m.get("image") if isinstance(m, dict) else m
        cap = m.get("caption") if isinstance(m, dict) else None
        if not img:
            continue
        doc = frappe.new_doc("Social Photo")
        doc.album = album
        doc.media_type = "Image"
        doc.image = img
        doc.caption = cap
        doc.uploaded_by = viewer
        doc.sort_order = base + i
        doc.insert(ignore_permissions=True)
        _attach_file(doc)
        created.append({"name": doc.name, "image": doc.image, "caption": doc.caption})
    frappe.db.commit()
    return {"photos": created, "photo_count": frappe.db.get_value("Social Album", album, "photo_count")}


@frappe.whitelist()
def add_video(album, video_url, caption=None):
    """Add an external video (YouTube/Vimeo) as a media item in the album."""
    viewer = require_login()
    if not _can_add(album, viewer):
        frappe.throw(frappe._("You can't add media to this album."), frappe.PermissionError)

    from es_social.social.video import parse_video_url
    info = parse_video_url(video_url)
    if not info:
        frappe.throw(frappe._("That video link isn't supported. Use a YouTube or Vimeo URL."))

    base = frappe.db.count("Social Photo", {"album": album})
    doc = frappe.new_doc("Social Photo")
    doc.album = album
    doc.media_type = "Video"
    doc.video_url = video_url
    doc.caption = caption
    doc.uploaded_by = viewer
    doc.sort_order = base
    doc.insert(ignore_permissions=True)

    # give the album a cover from the video thumbnail if it has none
    if info.get("thumbnail") and not frappe.db.get_value("Social Album", album, "cover_image"):
        frappe.db.set_value("Social Album", album, "cover_image", info["thumbnail"],
                            update_modified=False)

    frappe.db.commit()
    return {
        "name": doc.name, "media_type": "Video", "video_url": video_url,
        "video_embed": info["embed_url"],
        "photo_count": frappe.db.get_value("Social Album", album, "photo_count"),
    }


@frappe.whitelist()
def delete_photo(name):
    viewer = require_login()
    album, uploader = frappe.db.get_value("Social Photo", name, ["album", "uploaded_by"]) or (None, None)
    if not album or not (_owns(album, viewer) or uploader == viewer):
        frappe.throw(frappe._("You can only delete your own photos."), frappe.PermissionError)
    frappe.delete_doc("Social Photo", name, ignore_permissions=True, force=True)
    frappe.db.commit()
    return {"ok": True, "photo_count": frappe.db.get_value("Social Album", album, "photo_count")}


def _attach_file(photo_doc):
    if not photo_doc.image:
        return
    try:
        fname = frappe.db.get_value(
            "File", {"file_url": photo_doc.image, "attached_to_name": ["in", ["", None]]}, "name"
        )
        if fname:
            frappe.db.set_value("File", fname, {
                "attached_to_doctype": "Social Photo",
                "attached_to_name": photo_doc.name,
                "attached_to_field": "image",
            }, update_modified=False)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "es_social: album file attach failed")


@frappe.whitelist()
def reorder_photos(album, order):
    """order: JSON list of Social Photo names in the desired display order."""
    viewer = require_login()
    if not _owns(album, viewer):
        frappe.throw(frappe._("Only the album owner can reorder photos."), frappe.PermissionError)
    order = _load(order) or []
    valid = set(frappe.get_all("Social Photo", filters={"album": album}, pluck="name"))
    for i, name in enumerate([n for n in order if n in valid]):
        frappe.db.set_value("Social Photo", name, "sort_order", i, update_modified=False)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def set_cover(album, photo):
    viewer = require_login()
    if not _owns(album, viewer):
        frappe.throw(frappe._("Only the album owner can change the cover."), frappe.PermissionError)
    row = frappe.db.get_value("Social Photo", {"name": photo, "album": album}, ["image", "video_url"], as_dict=True)
    if not row:
        frappe.throw(frappe._("Photo not found in this album."))
    cover = row.image
    if not cover and row.video_url:
        from es_social.social.video import parse_video_url
        cover = (parse_video_url(row.video_url) or {}).get("thumbnail")
    frappe.db.set_value("Social Album", album, "cover_image", cover)
    frappe.db.commit()
    return {"ok": True, "cover_image": cover}


@frappe.whitelist(allow_guest=True)
def list_group_albums(group):
    from es_social.social.utils import get_viewer, get_group_ids
    viewer = get_viewer()
    privacy = frappe.db.get_value("Social Group", group, "privacy")
    if not privacy:
        frappe.throw(frappe._("Group not found."))
    if privacy != "Public" and (viewer == "Guest" or group not in get_group_ids(viewer)) \
            and not _is_privileged(viewer):
        return []
    return frappe.get_all("Social Album", filters={"group": group},
                          fields=["name", "title", "slug", "cover_image", "photo_count", "posted_on"],
                          order_by="posted_on desc")
