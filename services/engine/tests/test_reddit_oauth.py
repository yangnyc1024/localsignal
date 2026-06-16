from localsignal_engine.ingestion import reddit


def test_base_url_public_without_credentials(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    assert reddit._base_url() == "https://www.reddit.com"
    assert reddit._oauth_credentials() is None


def test_base_url_oauth_with_credentials(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    assert reddit._base_url() == "https://oauth.reddit.com"
    assert reddit._oauth_credentials() == ("cid", "secret")


def test_get_access_token_none_without_credentials(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    assert reddit._get_access_token() is None


def test_fetch_json_adds_bearer_header(monkeypatch):
    monkeypatch.setattr(reddit, "_get_access_token", lambda: "tok123")
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"ok": true}'

    def _fake_urlopen(request, timeout=20):
        captured["headers"] = request.headers
        return _Resp()

    monkeypatch.setattr(reddit.urllib.request, "urlopen", _fake_urlopen)
    result = reddit._fetch_json("https://oauth.reddit.com/r/test/search")
    assert result == {"ok": True}
    # urllib normalizes header keys to title-case
    assert captured["headers"].get("Authorization") == "Bearer tok123"


def test_token_cache_reused(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    reddit._token_cache["token"] = "cached"
    reddit._token_cache["expires_at"] = reddit.time.time() + 1000
    calls = {"n": 0}

    def _fake_urlopen(request, timeout=20):  # pragma: no cover - must not run
        calls["n"] += 1
        raise AssertionError("should not request a new token while cached")

    monkeypatch.setattr(reddit.urllib.request, "urlopen", _fake_urlopen)
    assert reddit._get_access_token() == "cached"
    assert calls["n"] == 0
    reddit._token_cache["token"] = None
    reddit._token_cache["expires_at"] = 0.0
