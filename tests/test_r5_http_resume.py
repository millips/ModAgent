"""Real localhost HTTP and new Python process, no external sources or game writes."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest
from modagent import downloader, task_control


def test_cancel_download_and_resume_partial_in_new_process(tmp_path):
    body = bytes(range(256)) * 1024
    ranges = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            value = self.headers.get('Range', '')
            ranges.append(value)
            start = int(value.split('=')[1].split('-')[0]) if value else 0
            self.send_response(206 if value else 200)
            self.send_header('Content-Length', str(len(body) - start))
            if value:
                self.send_header('Content-Range', f'bytes {start}-{len(body)-1}/{len(body)}')
            self.end_headers()
            try:
                self.wfile.write(body[start:])
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    dest = tmp_path / 'download.zip'
    url = f'http://127.0.0.1:{server.server_port}/fixture.zip'
    cancelled = threading.Event()
    try:
        with task_control.bind(cancelled.is_set):
            with pytest.raises(task_control.TaskCancelled):
                downloader.download_file(url, str(dest), lambda fraction: cancelled.set())
        assert not dest.exists()
        partial = Path(str(dest) + '.part')
        size = partial.stat().st_size
        assert 0 < size < len(body)
        # No background/new-turn continuation: only this explicit new process resumes.
        env = {**os.environ, 'MODAGENT_DATA_DIR': str(tmp_path / 'other-profile'), 'PYTHONIOENCODING': 'utf-8'}
        code = ('import sys; from modagent.downloader import download_file; '
                'download_file(sys.argv[1],sys.argv[2])')
        subprocess.run([sys.executable, '-c', code, url, str(dest)],
                       env=env, check=True, capture_output=True, timeout=15)
        assert ranges == ['', f'bytes={size}-']
        assert hashlib.sha256(dest.read_bytes()).digest() == hashlib.sha256(body).digest()
        assert not partial.exists()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)
