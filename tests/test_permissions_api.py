"""Per-service permission gating, and asking the menubar app for prompts."""
from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from icloudbridge.api.app import app
from icloudbridge.api.routes import system
from icloudbridge.sources.photos.photokit_bridge import PhotoKitBridgeClient, PhotoKitUnavailable


async def permissions_for(tmp_path, monkeypatch, granted: dict[str, bool]):
    (tmp_path / "permissions.json").write_text(json.dumps(granted))
    monkeypatch.setattr(system, "_check_full_disk_access_live", lambda: None)
    monkeypatch.setattr(system, "_check_reminders_live", lambda: None)
    config = SimpleNamespace(general=SimpleNamespace(data_dir=tmp_path))
    return await system.get_permissions(config)


async def test_photos_needs_photos_automation(tmp_path, monkeypatch):
    perms = await permissions_for(tmp_path, monkeypatch, {"photos_automation": True})

    assert not perms.photos.permitted
    assert perms.photos.missing == ["Apple Photos automation"]


async def test_notes_no_longer_needs_accessibility(tmp_path, monkeypatch):
    perms = await permissions_for(
        tmp_path, monkeypatch, {"full_disk_access": True, "notes_automation": True, "accessibility": False}
    )

    assert perms.notes.permitted


def test_permission_request_is_passed_to_the_menubar_app(monkeypatch):
    asked = []

    async def fake_request(self, service):
        asked.append(service)

    monkeypatch.setattr(PhotoKitBridgeClient, "request_permissions", fake_request)
    response = TestClient(app).post("/api/system/permissions/request", json={"service": "photos"})

    assert response.status_code == 200
    assert asked == ["photos"]


def test_permission_request_explains_a_missing_menubar_app(monkeypatch):
    async def unavailable(self, service):
        raise PhotoKitUnavailable("handshake not found")

    monkeypatch.setattr(PhotoKitBridgeClient, "request_permissions", unavailable)
    response = TestClient(app).post("/api/system/permissions/request", json={"service": "notes"})

    assert response.status_code == 503
    assert "menu bar app" in response.json()["detail"]
