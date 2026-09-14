# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Album + album-photo management."""

import json

import frappe
from frappe.utils import cint

from es_social.social.utils import require_login, check_content

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


@frappe.whitelist()
def create_album(title, description=None, privacy="Public", cover_image=None):
    viewer = require_login()
    check_content(title)
    doc = frappe.new_doc("Social Album")
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


@frappe.whitelist()
def list_albums(user=None, slug=None):
    """Albums of a user that the viewer may see (permission conditions applied)."""
    viewer = require_login()
    if slug:
        user = frappe.db.get_value("Social Profile", {"profile_slug": slug}, "user")
    user = user or viewer
    albums = frappe.get_list(
        "Social Album",
        filters={"owner_user": user},
        fields=["name", "title", "slug", "privacy", "cover_image", "photo_count", "posted_on"],
        order_by="posted_on desc",
    )
    return {
        "albums": albums,
        "user": user,
        "is_self": user == viewer,
    }


@frappe.whitelist()
def get_album(album=None, slug=None, start=0, page_length=200):
    viewer = require_login()
    if slug and not album:
        album = frappe.db.get_value("Social Album", {"slug": slug}, "name")
    if not album:
        frappe.throw(frappe._("Album not found."))
    if not frappe.has_permission("Social Album", "read", doc=album, user=viewer):
        frappe.throw(frappe._("You can't view this album."), frappe.PermissionError)

    doc = frappe.get_doc("Social Album", album)
    data = doc.get_public_dict()
    data["is_owner"] = (doc.owner_user == viewer) or _is_privileged(viewer)
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
    return data


@frappe.whitelist()
def add_photos(album, media):
    """media: list of {image, caption} (or bare url strings)."""
    viewer = require_login()
    if not _owns(album, viewer):
        frappe.throw(frappe._("You can only add photos to your own albums."), frappe.PermissionError)
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
    if not _owns(album, viewer):
        frappe.throw(frappe._("You can only add media to your own albums."), frappe.PermissionError)

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
    album = frappe.db.get_value("Social Photo", name, "album")
    if not album or not _owns(album, viewer):
        frappe.throw(frappe._("You can only delete photos from your own albums."), frappe.PermissionError)
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
