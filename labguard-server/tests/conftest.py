import os
import sys
from pathlib import Path

CLIENT_SRC = Path(__file__).parents[2] / "labguard-client" / "src"
sys.path.insert(0, str(CLIENT_SRC))

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from labguard_server.config import Settings
from labguard_server.main import create_app
from labguard_server.models import Administrator
from labguard_server.security import hash_password


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "test.sqlite"
    database_url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-that-is-at-least-32-chars")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    command.upgrade(config, "head")

    app = create_app(Settings(database_url, "test-session-secret-that-is-at-least-32-chars", cookie_secure=False,
                              app_env="test", heartbeat_interval_seconds=0.1, delayed_after_seconds=0.25,
                              offline_after_seconds=0.5))
    with TestClient(app) as test_client:
        with app.state.session_factory.begin() as db:
            db.add(Administrator(username="admin", password_hash=hash_password("correct-horse-battery-staple"), role="SUPER_ADMIN"))
            db.add(Administrator(username="viewer", password_hash=hash_password("viewer-password-123"), role="VIEWER"))
        yield test_client


def login(client, username="admin", password="correct-horse-battery-staple"):
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]

