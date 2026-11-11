import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')

from modagent import nexus


@pytest.fixture
def api_server():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            try:
                if self.path == '/drip':
                    self.wfile.write(b'{"value":"'); self.wfile.flush()
                    for _ in range(40):
                        self.wfile.write(b'a'); self.wfile.flush()
                        time.sleep(0.03)
                    self.wfile.write(b'"}')
                elif self.path == '/oversize':
                    self.wfile.write(json.dumps({'value':'a' * 2048}).encode())
                else:
                    self.wfile.write(b'{"files":[{"file_id":7}]}')
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_api_body_drip_has_total_budget(monkeypatch, api_server):
    monkeypatch.setattr(nexus, '_API_BODY_DEADLINE', 0.15, raising=False)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        nexus._api(api_server + '/drip', 'synthetic')
    assert time.monotonic() - started < 0.9


def test_api_body_size_is_bounded(monkeypatch, api_server):
    monkeypatch.setattr(nexus, '_API_MAX_BYTES', 128, raising=False)
    with pytest.raises(ValueError, match='NEXUS_RESPONSE_TOO_LARGE'):
        nexus._api(api_server + '/oversize', 'synthetic')


def test_api_body_normal_json(api_server):
    assert nexus._api(api_server + '/ok', 'synthetic') == {'files':[{'file_id':7}]}
