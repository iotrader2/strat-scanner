import os

from fastapi.testclient import TestClient

from strat import api, logos

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'


def test_normalize_accepts_tickers_and_rejects_paths():
    assert logos.normalize(" brk-b ") == "BRK-B"
    assert logos.normalize("BF.B") == "BF.B"
    for bad in ("", "../etc", "A/B", "TOOLONGTICKER1", "-X", "a b"):
        assert logos.normalize(bad) is None


def test_sniff_keeps_images_and_drops_html():
    assert logos.sniff(PNG) == ("png", "image/png")
    assert logos.sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ("webp", "image/webp")
    assert logos.sniff(SVG) == ("svg", "image/svg+xml")
    assert logos.sniff(b"<html>not found</html>") is None
    assert logos.sniff(b"") is None


def test_fetches_once_then_serves_from_disk(tmp_path):
    calls = []

    def fetch(sym):
        calls.append(sym)
        return PNG

    first = logos.get_logo("aapl", root=tmp_path, fetch=fetch)
    again = logos.get_logo("AAPL", root=tmp_path, fetch=fetch)
    assert first == again and first.media_type == "image/png"
    assert first.path == tmp_path / "AAPL.png" and first.path.read_bytes() == PNG
    assert calls == ["AAPL"]


def test_a_miss_is_remembered_for_a_day(tmp_path):
    calls = []

    def fetch(sym):
        calls.append(sym)
        return None

    assert logos.get_logo("ZZZZ", root=tmp_path, fetch=fetch, now=1_000_000) is None
    os.utime(tmp_path / "ZZZZ.miss", (1_000_000, 1_000_000))
    assert logos.get_logo("ZZZZ", root=tmp_path, fetch=fetch, now=1_000_000 + 3600) is None
    assert calls == ["ZZZZ"]
    # After a day it asks again (a new listing may have gained a logo).
    assert logos.get_logo("ZZZZ", root=tmp_path, fetch=lambda s: PNG, now=1_000_000 + 2 * 86400) is not None
    assert not (tmp_path / "ZZZZ.miss").exists()


def test_network_errors_are_not_cached_as_misses(tmp_path):
    def boom(sym):
        raise OSError("down")

    assert logos.get_logo("MSFT", root=tmp_path, fetch=boom) is None
    assert not (tmp_path / "MSFT.miss").exists()


def test_invalid_symbols_never_fetch(tmp_path):
    assert logos.get_logo("../../x", root=tmp_path, fetch=lambda s: PNG) is None
    assert list(tmp_path.iterdir()) == []


def test_endpoint_serves_png_with_long_cache_and_404_on_miss(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "LOGO_DIR", tmp_path)
    (tmp_path / "AAPL.png").write_bytes(PNG)
    (tmp_path / "MRVL.svg").write_bytes(SVG)
    (tmp_path / "ZZZZ.miss").touch()
    client = TestClient(api.app)
    r = client.get("/api/logo/AAPL")
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert "max-age=604800" in r.headers["cache-control"]
    svg = client.get("/api/logo/mrvl")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in svg.headers["content-security-policy"]
    miss = client.get("/api/logo/ZZZZ")
    assert miss.status_code == 404 and "max-age=86400" in miss.headers["cache-control"]
    assert client.get("/api/logo/..%2F..%2Fetc").status_code == 404
