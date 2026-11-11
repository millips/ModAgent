"""Real local HTTP response validation; only temporary download files."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from modagent import downloader


@pytest.mark.parametrize('mode', ['valid', 'ignored-range', 'wrong-start', 'missing-range', 'wrong-length', 'invalid-end', 'oversized-body', 'overrun-range', 'changed-total'])
def test_resume_validates_response_before_appending(tmp_path, mode):
    payload = b'0123456789abcdef'
    destination = tmp_path / 'download.zip'
    destination.write_bytes(b'previous-complete-download')
    partial = tmp_path / 'download.zip.part'
    partial.write_bytes(payload[:4])
    hits = []
    reported = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            hits.append(self.headers.get('Range'))
            if mode == 'changed-total':
                first = len(hits) == 1
                body = payload[4:8] if first else b'changed-data'
                self.send_response(206)
                self.send_header('Content-Range', 'bytes 4-7/16' if first else 'bytes 8-19/20')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = payload if mode in {'wrong-start', 'ignored-range'} else payload[4:]
            if mode == 'oversized-body':
                body += b'unexpected-extra-bytes'
            self.send_response(200 if mode == 'ignored-range' else 206)
            if mode not in {'missing-range', 'ignored-range'}:
                start = 0 if mode == 'wrong-start' else 4
                end = 16 if mode == 'invalid-end' else 7 if mode == 'overrun-range' else 15
                self.send_header('Content-Range', f'bytes {start}-{end}/16')
            if mode not in {'oversized-body', 'overrun-range'}:
                self.send_header('Content-Length', str(len(body) + (1 if mode == 'wrong-length' else 0)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}/fixture'
        if mode in {'valid', 'ignored-range'}:
            downloader.download_file(url, str(destination))
            assert destination.read_bytes() == payload
            assert not partial.exists()
        else:
            with pytest.raises(downloader.DownloadFailure) as failure:
                downloader.download_file(url, str(destination), reported.append)
            assert failure.value.failure_kind == 'invalid_resume_response'
            assert destination.read_bytes() == b'previous-complete-download'
            assert partial.read_bytes() == payload[:8 if mode == 'changed-total' else 4]
            assert 1.0 not in reported, 'Invalid response must not report complete progress'
        assert hits == (['bytes=4-', 'bytes=8-'] if mode == 'changed-total' else ['bytes=4-'])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
