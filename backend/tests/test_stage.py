"""Staging basic auth and built-UI serving (both off unless configured)."""

import base64

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from strat.stage import COOKIE_NAME, BasicAuthMiddleware, cookie_value, mount_ui


def _basic(user: str, password: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def _app(tmp_path, monkeypatch, creds=None, token=None):
    if token:
        monkeypatch.setenv("STAGE_TOKEN", token)
    else:
        monkeypatch.delenv("STAGE_TOKEN", raising=False)
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


TOKEN = "t0ken-For-Tests_abcdefghijklmnopqrstuvwxyz"


def _cookie(token=TOKEN) -> dict:
    return {"Cookie": f"{COOKIE_NAME}={cookie_value(token)}"}


def test_token_mode_hides_everything_without_cookie(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, creds=("stage", "s3cret"), token=TOKEN)
    for path in ("/", "/themes", "/assets/app.js", "/api/ping", "/favicon.ico"):
        r = client.get(path)
        assert r.status_code == 404, path
        assert "www-authenticate" not in r.headers
    # Basic auth is off in token mode, even with the right credentials.
    assert client.get("/api/ping", headers=_basic("stage", "s3cret")).status_code == 404
    assert client.get("/", headers=_cookie("wrong-token")).status_code == 404
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()


def test_wrong_link_is_404(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, token=TOKEN)
    for path in ("/k/nope", "/k/", "/?k=nope", "/k/" + TOKEN[:-1]):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 404, path
        assert "set-cookie" not in r.headers


@pytest.mark.parametrize("link", ["/k/" + TOKEN, "/?k=" + TOKEN, "/k/" + TOKEN + "/"])
def test_secret_link_sets_cookie_and_redirects(tmp_path, monkeypatch, link):
    client = _app(tmp_path, monkeypatch, token=TOKEN)
    r = client.get(link, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE_NAME}={cookie_value(TOKEN)};")
    assert TOKEN not in cookie
    for attr in ("HttpOnly", "Secure", "SameSite=lax", "Max-Age=34560000", "Path=/"):
        assert attr.lower() in cookie.lower(), attr


def test_cookie_unlocks_ui_api_and_websocket(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch, token=TOKEN)
    h = {**_cookie(), "Cookie": "other=1; " + _cookie()["Cookie"]}
    assert client.get("/", headers=h).text == "<html>ui</html>"
    assert client.get("/assets/app.js", headers=h).status_code == 200
    assert client.get("/api/ping", headers=h).json() == {"ok": True}
    with client.websocket_connect("/ws", headers=h) as ws:
        assert ws.receive_json()["type"] == "snapshot"
