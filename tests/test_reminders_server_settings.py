"""Reminders server settings as the Settings page sees them (issue #20)."""
from __future__ import annotations

import pytest

from icloudbridge.api.models import ConfigUpdateRequest
from icloudbridge.api.routes import config as config_routes
from icloudbridge.core.config import AppConfig


def make_config(tmp_path, **reminders) -> AppConfig:
    return AppConfig(general={"data_dir": tmp_path}, reminders=reminders)


@pytest.mark.parametrize(
    ("caldav_url", "use_nextcloud", "nextcloud_url"),
    [
        (None, True, None),
        ("https://cloud.example.com/remote.php/dav", True, "https://cloud.example.com"),
        ("https://cloud.example.com/remote.php/dav/", True, "https://cloud.example.com"),
        ("https://nas.example.com:5001/caldav/", False, None),
        ("https://caldav.icloud.com", False, None),
        # Not what the Nextcloud form builds, so it must stay editable as a custom URL
        ("https://cloud.example.com/remote.php/dav/calendars/me/", False, None),
    ],
)
async def test_nextcloud_mode_is_read_off_the_caldav_url(tmp_path, caldav_url, use_nextcloud, nextcloud_url):
    response = await config_routes.get_config(make_config(tmp_path, caldav_url=caldav_url))

    assert response.reminders_use_nextcloud is use_nextcloud
    assert response.reminders_nextcloud_url == nextcloud_url


async def test_stored_password_is_reported_without_revealing_it(tmp_path, monkeypatch):
    monkeypatch.setattr(
        config_routes.CredentialStore, "has_caldav_password", lambda self, username: username == "me"
    )

    response = await config_routes.get_config(make_config(tmp_path, caldav_username="me"))

    assert response.reminders_caldav_password_set is True
    assert "reminders_caldav_password" not in response.model_dump()


async def test_saving_returns_the_same_settings_as_reading(tmp_path):
    """The page reloads its form from the save response; a gap there reverts settings."""
    config = make_config(tmp_path, caldav_url="https://nas.example.com:5001/caldav/")
    config.passwords.provider = "nextcloud"
    config.passwords.nextcloud_url = "https://cloud.example.com"
    config.passwords.nextcloud_username = "me"

    saved = await config_routes.update_config(ConfigUpdateRequest(notes_enabled=False), config)
    read = await config_routes.get_config(config)

    assert saved == read
    assert saved.passwords_provider == "nextcloud"
