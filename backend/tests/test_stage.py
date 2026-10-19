"""Staging basic auth and built-UI serving (both off unless configured)."""

import base64

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from strat.stage import BasicAuthMiddleware, mount_ui


def _basic(user: str, password: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def _app(tmp_path, monkeypatch, creds=None):
    if creds:
        monkeypatch.setenv("STAGE_USER", creds[0])
        monkeypatch.setenv("STAGE_PASS", creds[1])
    else:
        monkeypatch.delenv("STAGE_USER", raising=False)
        monkeypatch.delenv("STAGE_PASS", raising=False)
    app = FastAPI()
    app.add_middleware(BasicAuthMiddleware)

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"type": "snapshot"})
        await websocket.close()

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>ui</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (dist / "favicon.ico").write_text("ico")
    assert mount_ui(app, dist)
    return TestClient(app)


def test_auth_off_without_env(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    assert client.get("/api/ping").status_code == 200
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "snapshot"


def test_auth_required_when_env_set(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, ("stage", "s3cret"))
    r = client.get("/api/ping")
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Basic")
    assert client.get("/", headers=_basic("stage", "wrong")).status_code == 401
    assert client.get("/api/ping", headers=_basic("stage", "s3cret")).json() == {"ok": True}
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
    with client.websocket_connect("/ws", headers=_basic("stage", "s3cret")) as ws:
        assert ws.receive_json()["type"] == "snapshot"


def test_ui_serving(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    assert client.get("/").text == "<html>ui</html>"
    assert client.get("/themes/some-route").text == "<html>ui</html>"
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/favicon.ico").text == "ico"
    assert client.get("/api/missing").status_code == 404
    assert client.get("/api/ping").json() == {"ok": True}
