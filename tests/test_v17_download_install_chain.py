"""Real localhost bytes and temporary files; no model, external site or real game."""
import errno
import hashlib
import io
import os
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from modagent import downloader, installer, task_control


@pytest.mark.parametrize('fault', ['none', 'corrupt', 'permission', 'cancel'])
def test_download_install_chain(tmp_path, monkeypatch, fault):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as package:
        package.writestr('a.txt', b'new-a')
        package.writestr('b.txt', b'new-b')
    payload = b'not a zip archive' if fault == 'corrupt' else archive.getvalue()
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    game = tmp_path / 'game'
    game.mkdir()
    (game / 'a.txt').write_bytes(b'original-a')
    (game / 'unrelated.txt').write_bytes(b'keep-user-file')
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    downloaded = tmp_path / 'download.zip'
    try:
        downloader.download_file(f'http://127.0.0.1:{server.server_port}/fixture.zip', str(downloaded))
        assert hits == ['/fixture.zip']
        assert hashlib.sha256(downloaded.read_bytes()).digest() == hashlib.sha256(payload).digest()
        assert not (tmp_path / 'download.zip.part').exists()
        cancelled = threading.Event()
        replace = os.replace
        commits = []

        def guarded_replace(src, dest):
            if os.path.basename(os.path.dirname(src)) == 'stage':
                commits.append(str(dest))
                if fault == 'permission' and len(commits) == 2:
                    raise PermissionError(errno.EACCES, 'fixture permission denied', str(dest))
            result = replace(src, dest)
            if fault == 'cancel' and len(commits) == 1:
                cancelled.set()
            return result

        monkeypatch.setattr(installer.os, 'replace', guarded_replace)
        mapping = {'a.txt': 'a.txt', 'b.txt': 'b.txt'}
        with task_control.bind(cancelled.is_set):
            if fault == 'corrupt':
                with pytest.raises(RuntimeError, match='解压失败'):
                    installer.install_mod_custom(str(downloaded), str(game), 'fixture', mapping)
            else:
                result = installer.install_mod_custom(str(downloaded), str(game), 'fixture', mapping)
                if fault == 'none':
                    assert len(result['installed']) == 2
                    assert not result['errors']
                    assert (game / 'a.txt').read_bytes() == b'new-a'
                    assert (game / 'b.txt').read_bytes() == b'new-b'
                    backup = installer._backup_lookup(str(game / 'a.txt'), str(game), 'fixture')
                    with open(backup, 'rb') as original:
                        assert original.read() == b'original-a'
                else:
                    assert not result['installed']
                    assert result['errors'], 'Failure must not be reported as a successful installation'
                    assert commits, 'Fault injection must reach the real commit path'
        if fault != 'none':
            assert (game / 'a.txt').read_bytes() == b'original-a'
            assert not (game / 'b.txt').exists()
        assert (game / 'unrelated.txt').read_bytes() == b'keep-user-file'
        assert not list(game.glob('.modagent-transaction-*'))
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)
