import urllib.error
import ssl

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


def test_certificate_failure_is_not_retried_or_bypassed(monkeypatch, tmp_path):
    calls = []
    def fail(*args, **kwargs):
        calls.append(kwargs['context'])
        raise urllib.error.URLError(ssl.SSLCertVerificationError('untrusted certificate'))
    monkeypatch.setattr(downloader.urllib.request, 'urlopen', fail)
    with pytest.raises(downloader.DownloadFailure) as captured:
        downloader.download_file('https://example.invalid/mod.zip', str(tmp_path / 'mod.zip'))
    assert len(calls) == 1
    assert calls[0].verify_mode == ssl.CERT_REQUIRED
    assert calls[0].check_hostname
    assert captured.value.failure_kind == 'certificate_verification_failed'
    assert not captured.value.retryable


def test_unknown_length_read_failure_keeps_partial_not_success(monkeypatch, tmp_path):
    class Response:
        status = 200
        headers = {}
        reads = 0
        closed = False
        def read(self, size):
            self.reads += 1
            if self.reads == 1:
                return b'incomplete archive'
            raise TimeoutError('read interrupted')
        def close(self):
            self.closed = True
    response = Response()
    monkeypatch.setattr(downloader.urllib.request, 'urlopen', lambda *a, **kw: response)
    dest = tmp_path / 'mod.zip'
    with pytest.raises(downloader.DownloadFailure) as captured:
        downloader.download_file('https://example.invalid/mod.zip', str(dest))
    assert captured.value.failure_kind == 'read_interrupted'
    assert not dest.exists()
    assert dest.with_suffix('.zip.part').read_bytes() == b'incomplete archive'
    assert response.closed
