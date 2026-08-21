from app.main import app
from app.models.models import Base
from app.routers.mobile_updates import _is_newer, _version_key


def test_mobile_update_schema_has_immutable_bundle_metadata_and_channel_pointers():
    bundles = Base.metadata.tables["mobile_update_bundles"]
    channels = Base.metadata.tables["mobile_update_channels"]
    assert {"app_id", "version", "storage_key", "checksum", "size", "created_at"}.issubset(bundles.c.keys())
    assert {"app_id", "name", "active_bundle_id", "previous_bundle_id", "updated_at"}.issubset(channels.c.keys())
    assert bundles.c.storage_key.unique is True


def test_mobile_update_versions_are_monotonic_and_builtin_is_supported():
    assert _version_key("1.2.10") == (1, 2, 10)
    assert _version_key("builtin") is None
    assert _is_newer("1.0.1", "builtin")
    assert _is_newer("1.0.2", "1.0.1")
    assert not _is_newer("1.0.1", "1.0.1")
    assert not _is_newer("1.0.0", "1.0.1")


def test_mobile_update_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert "/v1/mobile-updates/check" in paths
    assert "/v1/mobile-updates/bundles/{version}" in paths
    assert "/v1/mobile-updates/channels/{channel}/rollback" in paths
