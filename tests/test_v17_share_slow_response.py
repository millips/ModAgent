import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Use isolated MODAGENT_DATA_DIR')
from modagent import share_config as share


@pytest.mark.parametrize('mode', ['normal', 'slow', 'truncated', 'no-length', 'oversize', 'bad-length'])
def test_real_http_body_deadline_and_cleanup(monkeypatch,mode):
    slow = mode == 'slow'
    body=json.dumps({'schema':share.SCHEMA,'kind':'player_share','game':{},'mods':[]}).encode()
    stopped=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            self.send_response(200)
            if mode!='no-length':
                self.send_header('Content-Length','invalid' if mode=='bad-length' else str(share.MAX_SHARE_BYTES+1 if mode=='oversize' else len(body)+(10 if mode=='truncated' else 0)))
            self.end_headers()
            try:
                if slow:
                    for byte in body:
                        self.wfile.write(bytes([byte]));self.wfile.flush();time.sleep(.02)
                else:self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, OSError):pass
            finally:stopped.set()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    captured=[]
    def local_open(request,timeout):
        response=urlopen(f'http://127.0.0.1:{server.server_port}/share',timeout=timeout)
        captured.append(response)
        return response
    monkeypatch.setattr(share,'urlopen',local_open)
    monkeypatch.setattr(share,'SHARE_READ_BUDGET_SECONDS',.12 if slow else 2)
    started=time.monotonic()
    try:
        if slow:
            with pytest.raises(share.ShareError,match='too long'):
                share._read_remote_share('https://raw.githubusercontent.com/fixture/test/share.json')
            assert time.monotonic()-started<1
        elif mode=='truncated':
            with pytest.raises(share.ShareError,match='incomplete'):
                share._read_remote_share('https://raw.githubusercontent.com/fixture/test/share.json')
        elif mode in ('oversize','bad-length'):
            with pytest.raises(share.ShareError,match='too large' if mode=='oversize' else 'invalid content length'):
                share._read_remote_share('https://raw.githubusercontent.com/fixture/test/share.json')
        else:
            assert json.loads(share._read_remote_share('https://raw.githubusercontent.com/fixture/test/share.json'))['mods']==[]
        assert captured[0].closed
        assert stopped.wait(2),'Server kept sending after client closed'
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
