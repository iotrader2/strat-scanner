"""STRAT_FETCH_SUBPROCESS routes the refresh through the child-process fetcher."""

from strat import api, data, fetch_worker


def test_enabled_flag(monkeypatch):
    monkeypatch.delenv("STRAT_FETCH_SUBPROCESS", raising=False)
    assert not fetch_worker.enabled()
    monkeypatch.setenv("STRAT_FETCH_SUBPROCESS", "1")
    assert fetch_worker.enabled()


def test_refresh_uses_child_when_enabled(monkeypatch):
    calls = []
    monkeypatch.setenv("STRAT_FETCH_SUBPROCESS", "1")
    monkeypatch.setattr(fetch_worker, "fetch_in_child", lambda *a: calls.append(a[:3]))
    monkeypatch.setattr(data, "refresh", lambda *a, **k: (_ for _ in ()).throw(AssertionError("in-process fetch")))
    monkeypatch.setattr(api, "_ensure_scan", lambda force=False: [])
    api._run_refresh(full=False, period="5d", with_earnings=False)
    assert calls == [(False, "5d", False)]
    assert api.State.error is None and api.State.refreshing is False


def test_child_error_surfaces_in_state(monkeypatch):
    monkeypatch.setenv("STRAT_FETCH_SUBPROCESS", "1")

    def boom(*a):
        raise RuntimeError("fetch process exited with code -9")

    monkeypatch.setattr(fetch_worker, "fetch_in_child", boom)
    monkeypatch.setattr(api, "_ensure_scan", lambda force=False: [])
    api._run_refresh(full=True)
    assert "exited" in api.State.error
    api.State.error = None
