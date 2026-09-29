"""Tests for the password-protected admin API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.storage import StoryStore
from tests.test_api import FakeGemini, wait_until_settled

PASSWORD = "test-password"
AUTH = {"X-Admin-Password": PASSWORD}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a configured admin password and an isolated story directory."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", PASSWORD)
    with TestClient(app) as test_client:
        app.state.gemini = FakeGemini()
        app.state.store = StoryStore(tmp_path)
        yield test_client


def test_login_with_correct_password(client: TestClient):
    assert client.post("/api/admin/login", headers=AUTH).status_code == 204


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Password": "wrong"}])
def test_wrong_or_missing_password_is_rejected(client: TestClient, headers: dict):
    assert client.post("/api/admin/login", headers=headers).status_code == 401
    assert client.get("/api/admin/stories", headers=headers).status_code == 401
    assert client.delete("/api/admin/stories/aaaaaaaaaaaa", headers=headers).status_code == 401


def test_admin_disabled_when_password_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    assert client.post("/api/admin/login", headers=AUTH).status_code == 503
    assert client.post("/api/admin/login", headers={"X-Admin-Password": ""}).status_code == 503


def test_list_shows_date_and_forwarded_ip_but_public_api_hides_ip(client: TestClient):
    created = client.post(
        "/api/stories", json={"character": "Elsa"}, headers={"X-Forwarded-For": "203.0.113.7"}
    ).json()
    wait_until_settled(client, created["id"])

    listing = client.get("/api/admin/stories", headers=AUTH).json()

    assert [entry["id"] for entry in listing] == [created["id"]]
    assert listing[0]["client_ip"] == "203.0.113.7"
    assert listing[0]["created_at"] == created["created_at"]
    assert "client_ip" not in created
    assert "client_ip" not in client.get(f"/api/stories/{created['id']}").json()
    assert "client_ip" not in client.get("/api/stories").json()["stories"][0]


def test_forwarded_for_uses_last_entry_added_by_proxy(client: TestClient):
    client.post(
        "/api/stories",
        json={"character": "Elsa"},
        headers={"X-Forwarded-For": "10.0.0.1, 198.51.100.4"},
    )
    assert client.get("/api/admin/stories", headers=AUTH).json()[0]["client_ip"] == "198.51.100.4"


def test_delete_story_removes_it(client: TestClient):
    created = client.post("/api/stories", json={"character": "Elsa"}).json()
    wait_until_settled(client, created["id"])

    assert client.delete(f"/api/admin/stories/{created['id']}", headers=AUTH).status_code == 204
    assert client.get(f"/api/stories/{created['id']}").status_code == 404
    assert client.get(f"/api/stories/{created['id']}/audio").status_code == 404
    assert client.get("/api/admin/stories", headers=AUTH).json() == []


def test_delete_missing_story_returns_404(client: TestClient):
    assert client.delete("/api/admin/stories/aaaaaaaaaaaa", headers=AUTH).status_code == 404
    assert client.delete("/api/admin/stories/not-an-id", headers=AUTH).status_code == 404


def test_delete_generating_story_returns_409(client: TestClient):
    story_id = app.state.store.save("Elsa", "Storia.", chunks_total=2)["id"]

    assert client.delete(f"/api/admin/stories/{story_id}", headers=AUTH).status_code == 409
    assert app.state.store.get(story_id) is not None


def test_admin_page_served(client: TestClient):
    response = client.get("/admin")
    assert response.status_code == 200
    assert "X-Admin-Password" in response.text
