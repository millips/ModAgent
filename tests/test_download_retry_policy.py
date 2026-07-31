import urllib.error

import pytest

from modagent import downloader


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.invalid/mod.zip",
        status,
        "test",
        hdrs=None,
        fp=None,
    )


def test_http_404_is_terminal_and_not_retried(monkeypatch, tmp_path):
    calls = 0

    def fail(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise _http_error(404)

    monkeypatch.setattr(downloader.urllib.request, "urlopen", fail)
    monkeypatch.setattr(downloader.time, "sleep", lambda _seconds: None)

    with pytest.raises(downloader.DownloadFailure) as captured:
        downloader.download_file(
            "https://example.invalid/mod.zip",
            str(tmp_path / "mod.zip"),
        )

    error = captured.value
    assert calls == 1
    assert error.failure_kind == "http_not_found"
    assert error.http_status == 404
    assert error.terminal is True
    assert error.retryable is False
    assert error.attempts == 1


def test_http_503_has_bounded_retries(monkeypatch, tmp_path):
    calls = 0

    def fail(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise _http_error(503)

    monkeypatch.setattr(downloader.urllib.request, "urlopen", fail)
    monkeypatch.setattr(downloader.time, "sleep", lambda _seconds: None)

    with pytest.raises(downloader.DownloadFailure) as captured:
        downloader.download_file(
            "https://example.invalid/mod.zip",
            str(tmp_path / "mod.zip"),
        )

    error = captured.value
    assert calls == 5
    assert error.failure_kind == "http_transient"
    assert error.http_status == 503
    assert error.terminal is False
    assert error.retryable is True
    assert error.attempts == 5


def test_network_failure_has_bounded_retries(monkeypatch, tmp_path):
    calls = 0

    def fail(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(downloader.urllib.request, "urlopen", fail)
    monkeypatch.setattr(downloader.time, "sleep", lambda _seconds: None)

    with pytest.raises(downloader.DownloadFailure) as captured:
        downloader.download_file(
            "https://example.invalid/mod.zip",
            str(tmp_path / "mod.zip"),
        )

    assert calls == 5
    assert captured.value.failure_kind == "network_transient"
    assert captured.value.retryable is True
    assert captured.value.attempts == 5
