from unittest.mock import MagicMock, patch

import pytest

from app.storage.supabase_reader import fetch_observations


@pytest.fixture
def settings(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "sb_publishable_test")
    monkeypatch.setenv("SUPABASE_TABLE", "observations")
    monkeypatch.setenv("SUPABASE_SCHEMA", "public")
    monkeypatch.setenv("SUPABASE_ORDER", "record_time.asc,id.asc")
    monkeypatch.delenv("SUPABASE_ACCESS_TOKEN", raising=False)
    return tmp_path / "missing.env"


def response(rows, status=200):
    result = MagicMock(status_code=status)
    result.json.return_value = rows
    return result


def test_pagination_continues_after_short_page(settings):
    with patch("app.storage.supabase_reader.requests.Session") as session:
        get = session.return_value.__enter__.return_value.get
        get.side_effect = [response([{"id": 1}, {"id": 2}]), response([{"id": 3}]), response([])]
        assert fetch_observations(settings) == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert [call.kwargs["params"]["offset"] for call in get.call_args_list] == [0, 2, 3]
        assert get.call_args.kwargs["params"]["order"] == "record_time.asc,id.asc"
        assert get.call_args.kwargs["headers"] == {"apikey": "sb_publishable_test", "Accept-Profile": "public"}


@pytest.mark.parametrize("key,token", [("eyJ.legacy.jwt", ""), ("sb_publishable_test", "user.jwt")])
def test_authentication_headers(settings, monkeypatch, key, token):
    monkeypatch.setenv("SUPABASE_KEY", key)
    monkeypatch.setenv("SUPABASE_ACCESS_TOKEN", token)
    with patch("app.storage.supabase_reader.requests.Session") as session:
        get = session.return_value.__enter__.return_value.get
        get.return_value = response([])
        fetch_observations(settings)
        assert get.call_args.kwargs["headers"]["Authorization"] == f"Bearer {token or key}"


def test_http_error_does_not_expose_key(settings):
    with patch("app.storage.supabase_reader.requests.Session") as session:
        session.return_value.__enter__.return_value.get.return_value = response({}, 403)
        with pytest.raises(RuntimeError, match="HTTP 403") as error:
            fetch_observations(settings)
        assert "sb_publishable_test" not in str(error.value)


def test_missing_credentials(settings, monkeypatch):
    monkeypatch.setenv("SUPABASE_KEY", "")
    with pytest.raises(ValueError, match="Fill in"):
        fetch_observations(settings)


@pytest.mark.parametrize("suffix", ["", "/", "/rest/v1", "/rest/v1/"])
def test_project_and_rest_urls_use_the_same_endpoint(settings, monkeypatch, suffix):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co" + suffix)
    with patch("app.storage.supabase_reader.requests.Session") as session:
        get = session.return_value.__enter__.return_value.get
        get.return_value = response([])
        fetch_observations(settings)
        assert get.call_args.args[0] == "https://example.supabase.co/rest/v1/observations"


def test_database_error_is_reported_without_credentials(settings, monkeypatch):
    monkeypatch.setenv("SUPABASE_ACCESS_TOKEN", "private.user.token")
    error = {
        "code": "PGRST205",
        "message": "Missing table observations: sb_publishable_test",
        "hint": "private.user.token",
    }
    with patch("app.storage.supabase_reader.requests.Session") as session:
        session.return_value.__enter__.return_value.get.return_value = response(error, 404)
        with pytest.raises(RuntimeError) as result:
            fetch_observations(settings)
        message = str(result.value)
        assert "PGRST205" in message
        assert "Missing table observations" in message
        assert "sb_publishable_test" not in message
        assert "private.user.token" not in message
