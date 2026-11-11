"""Offline tests for truthful connection results and bounded public probes."""
import asyncio
import socket
import ssl

import httpx
import pytest
from fastapi.testclient import TestClient

from modagent import connection_test as net


@pytest.mark.parametrize('code,status', [
    (200, 'reachable'), (204, 'reachable'), (302, 'redirect'),
    (401, 'auth_required'), (403, 'restricted'), (407, 'proxy_auth'),
    (404, 'http_error'), (429, 'rate_limited'), (503, 'service_error'),
])
def test_http_responses_are_not_all_network_failures(code, status):
    assert net.classify_status(code) == status


@pytest.mark.parametrize('error,status', [
    (httpx.ConnectTimeout('secret'), 'timeout'),
    (httpx.ProxyError('http://user:secret@proxy'), 'proxy_error'),
    (ValueError('socks4://secret'), 'configuration_error'),
    (httpx.ConnectError('secret'), 'connection_error'),
])
def test_error_text_is_not_returned(error, status):
    assert net.classify_exception(error) == status


@pytest.mark.parametrize('inner,status', [
    (socket.gaierror('secret'), 'dns_error'),
    (ssl.SSLCertVerificationError('secret'), 'tls_error'),
])
def test_nested_connection_error(inner, status):
    outer = httpx.ConnectError('redact me')
    outer.__cause__ = inner
    assert net.classify_exception(outer) == status


def test_probe_does_not_download_body_follow_redirects_or_send_secrets(monkeypatch):
    requests = []
    options = []

    class UnreadableBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError('Probe must not download response body')
            yield b''

    def handle(request):
        requests.append(request)
        return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'}, stream=UnreadableBody())

    client = httpx.AsyncClient

    def factory(**kwargs):
        options.append(kwargs)
        return client(**kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(net.httpx, 'AsyncClient', factory)
    result = asyncio.run(net.probe_target('github'))
    assert result['status'] == 'redirect'
    assert result['http_status'] == 302
    assert result['elapsed_ms'] >= 0
    assert result['checked_at']
    assert len(requests) == 1
    assert requests[0].url == 'https://api.github.com/'
    assert not {'authorization', 'cookie', 'apikey'} & set(requests[0].headers)
    assert options[0]['follow_redirects'] is False
    assert options[0]['trust_env'] is True
    assert 'github' not in net._active


def test_deadline_and_later_retry(monkeypatch):
    async def stalled(_request):
        await asyncio.sleep(1)
        return httpx.Response(200)

    client = httpx.AsyncClient
    monkeypatch.setattr(net, 'PROBE_TIMEOUT', .02)
    monkeypatch.setattr(net.httpx, 'AsyncClient', lambda **kw: client(**kw, transport=httpx.MockTransport(stalled)))
    result = asyncio.run(net.probe_target('nexus'))
    assert result['status'] == 'timeout'
    assert 'nexus' not in net._active


def test_cancellation_releases_busy_target(monkeypatch):
    async def scenario():
        started = asyncio.Event()

        async def stalled(_request):
            started.set()
            await asyncio.sleep(10)

        client = httpx.AsyncClient
        monkeypatch.setattr(net.httpx, 'AsyncClient', lambda **kw: client(**kw, transport=httpx.MockTransport(stalled)))
        task = asyncio.create_task(net.probe_target('github'))
        await started.wait()
        with pytest.raises(net.ProbeBusy):
            await net.probe_target('github')
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert 'github' not in net._active

    asyncio.run(scenario())


def test_all_targets_bounded_to_three_concurrent_connections(monkeypatch):
    async def scenario():
        monkeypatch.setattr(net, '_slots', asyncio.Semaphore(3))
        active = 0
        peak = 0

        async def respond(_request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(.01)
            active -= 1
            return httpx.Response(200)

        client = httpx.AsyncClient
        monkeypatch.setattr(net.httpx, 'AsyncClient', lambda **kw: client(**kw, transport=httpx.MockTransport(respond)))
        results = await asyncio.gather(*(net.probe_target(t['id']) for t in net.TARGETS))
        assert all(r['status'] == 'reachable' for r in results)
        assert peak == 3
        assert not net._active

    asyncio.run(scenario())


def test_api_auth_allowlist_and_busy(monkeypatch):
    from modagent import api
    monkeypatch.setattr(api, '_API_TOKEN', 'test-only-token')
    client = TestClient(api.app)
    assert client.get('/network/targets').status_code == 401
    assert client.post('/network/test', json={'target_id': 'github'}).status_code == 401
    headers = {'X-ModAgent-Token': 'test-only-token'}
    response = client.get('/network/targets', headers=headers)
    assert len(response.json()['targets']) == 7
    assert client.post('/network/test', headers=headers, json={'target_id': 'http://127.0.0.1'}).status_code == 400
    assert client.post('/network/test', headers=headers, json={'target_id': ''}).status_code == 422
    net._active.add('github')
    try:
        assert client.post('/network/test', headers=headers, json={'target_id': 'github'}).status_code == 409
    finally:
        net._active.discard('github')
