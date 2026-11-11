import os
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')

from modagent import nexus


@pytest.mark.parametrize('target', ['http://api.example/other', 'https://other.example/other',
    'https://api.example:444/other', 'https://api.example:0/other', 'https://user@api.example/other'])
def test_redirect_rejects_downgrade_host_port_and_userinfo(target):
    import io
    import urllib.request
    response = io.BytesIO(b'')
    with pytest.raises(urllib.error.HTTPError, match='NEXUS_REDIRECT_BLOCKED'):
        nexus._SameOriginApiRedirect().redirect_request(
            urllib.request.Request('https://api.example/start'), response, 302, 'redirect', {}, target)
    assert response.closed


@pytest.mark.parametrize('cross_origin', [False, True])
def test_authenticated_redirect_stays_on_original_origin(cross_origin):
    received = []
    class Destination(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            received.append(self.headers.get('apikey'))
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
    destination = ThreadingHTTPServer(('127.0.0.1', 0), Destination)
    class Source(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            assert self.headers.get('apikey') == 'synthetic-only'
            if self.path == '/ok':
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
                return
            location = f'http://127.0.0.1:{destination.server_port}/ok' if cross_origin else '/ok'
            self.send_response(302); self.send_header('Location', location); self.end_headers()
    source = ThreadingHTTPServer(('127.0.0.1', 0), Source)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (source,destination)]
    for thread in threads:
        thread.start()
    try:
        url = f'http://127.0.0.1:{source.server_port}/redirect'
        if cross_origin:
            with pytest.raises(urllib.error.HTTPError, match='NEXUS_REDIRECT_BLOCKED'):
                nexus._api(url, 'synthetic-only')
        else:
            assert nexus._api(url, 'synthetic-only') == {'ok':True}
        assert received == [], 'Never send API credentials to another origin'
    finally:
        for server in (source,destination):
            server.shutdown(); server.server_close()
        for thread in threads:
            thread.join(timeout=2)
