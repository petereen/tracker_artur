import asyncio
import io

import pytest
from PIL import Image

from app.core.enterprise_deps import build_actor_context
from app.main import app
from app.routers.announcements import AnnouncementCreate, AnnouncementPatch, MAX_GALLERY_IMAGES, can_edit
from app.services import announcement_media
from app.services.announcement_media import InvalidAnnouncementImage, encode_image, is_media_url, media_url, read_image, save_image

IMAGE = "/api/v1/announcements/media/" + "a" * 32 + ".jpg"


def actor(*roles, account_id=1):
    return build_actor_context(account_id=account_id, organization_id=1, employee_id=None, email="a@b.mn", locale="mn", roles=frozenset(roles))


def picture(mode="RGB", size=(40, 30), fmt="PNG"):
    output = io.BytesIO()
    Image.new(mode, size, (200, 10, 10, 120)[: len(mode)]).save(output, format=fmt)
    return output.getvalue()


def test_routes_are_registered():
    paths = {(route.path, method) for route in app.routes for method in getattr(route, "methods", ())}
    for expected in [
        ("/v1/announcements", "GET"), ("/v1/announcements", "POST"), ("/v1/announcements/manage", "GET"),
        ("/v1/announcements/images", "POST"), ("/v1/announcements/media/{name}", "GET"),
        ("/v1/announcements/{announcement_id}", "PATCH"), ("/v1/announcements/{announcement_id}", "DELETE"),
    ]:
        assert expected in paths


def test_create_defaults_to_a_draft_and_trims_text():
    data = AnnouncementCreate(title="  Шинэ журам  ", summary="  ", category=" HR ")
    assert (data.title, data.summary, data.category, data.status, data.is_pinned) == ("Шинэ журам", None, "HR", "draft", False)


@pytest.mark.parametrize("bad", [
    {"title": "   "},
    {"title": "x" * 201},
    {"title": "ok", "status": "scheduled"},
    {"title": "ok", "cover_url": "https://evil.example/pixel.png"},
    {"title": "ok", "image_urls": ["/api/v1/announcements/media/../../etc/passwd"]},
    {"title": "ok", "image_urls": [IMAGE[:-5] + f"{index:x}.jpg" for index in range(MAX_GALLERY_IMAGES + 1)]},
    {"title": "ok", "body": "x" * 20_001},
])
def test_create_rejects_invalid_input(bad):
    with pytest.raises(ValueError):
        AnnouncementCreate.model_validate(bad)


def test_images_must_be_own_uploads_and_are_deduplicated():
    data = AnnouncementCreate(title="ok", cover_url=IMAGE, image_urls=[IMAGE, IMAGE])
    assert data.cover_url == IMAGE
    assert data.image_urls == [IMAGE]


def test_patch_only_carries_sent_fields():
    assert AnnouncementPatch(status="published").model_dump(exclude_unset=True) == {"status": "published"}
    assert AnnouncementPatch(cover_url=None).model_dump(exclude_unset=True) == {"cover_url": None}
    with pytest.raises(ValueError):
        AnnouncementPatch(title=" ")


def test_edit_permissions():
    assert can_edit(actor("admin"), 99)
    assert can_edit(actor("manager"), None)
    assert can_edit(actor("team_lead", account_id=7), 7)
    assert not can_edit(actor("team_lead", account_id=7), 8)
    assert not can_edit(actor("member", account_id=7), 7)


def test_encode_image_reencodes_and_scales(monkeypatch):
    monkeypatch.setattr(announcement_media.settings, "ANNOUNCEMENT_IMAGE_MAX_PIXELS", 20)
    encoded, extension, width, height = encode_image(picture(size=(40, 30), fmt="JPEG"), "image/jpeg")
    assert (extension, width, height) == ("jpg", 20, 15)
    assert Image.open(io.BytesIO(encoded)).format == "JPEG"
    # Transparency is kept as PNG.
    assert encode_image(picture(mode="RGBA"), "image/png")[1] == "png"


@pytest.mark.parametrize("content,content_type", [
    (b"not an image", "image/png"),
    (b"", "image/png"),
    (picture(), "image/svg+xml"),
])
def test_encode_image_rejects_bad_uploads(content, content_type):
    with pytest.raises(InvalidAnnouncementImage):
        encode_image(content, content_type)


def test_encode_image_rejects_oversized_uploads(monkeypatch):
    monkeypatch.setattr(announcement_media.settings, "ANNOUNCEMENT_IMAGE_MAX_BYTES", 10)
    with pytest.raises(InvalidAnnouncementImage):
        encode_image(picture(), "image/png")


def test_saved_image_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(announcement_media.settings, "ANNOUNCEMENT_IMAGE_DIR", str(tmp_path))
    name, width, height, size = asyncio.run(save_image(picture(), "image/png"))
    assert is_media_url(media_url(name))
    content, media_type = asyncio.run(read_image(name))
    assert (media_type, len(content), width, height) == ("image/jpeg", size, 40, 30)
    for hostile in ["../secret.jpg", "x.jpg", name.replace(".jpg", ".svg"), ""]:
        with pytest.raises(FileNotFoundError):
            asyncio.run(read_image(hostile))
