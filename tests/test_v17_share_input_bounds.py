import base64
import json
import os
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Set isolated MODAGENT_DATA_DIR first')
from modagent import share_config as share


def test_pasted_utf8_size_checked_before_json(monkeypatch):
    raw='{"padding":"'+'汉'*(share.MAX_SHARE_BYTES//2)+'"}'
    monkeypatch.setattr(share.json,'loads',lambda *a: pytest.fail('Oversize input reached parser'))
    with pytest.raises(share.ShareError,match='too large'):
        share.load_share_input(raw)


def test_offline_limit_checked_before_decode(monkeypatch):
    monkeypatch.setattr(share.base64,'b64decode',lambda *a,**k: pytest.fail('Oversize input reached decoder'))
    with pytest.raises(share.ShareError,match='too large'):
        share.load_share_input('data:application/json;base64,'+'A'*(4*((share.MAX_SHARE_BYTES+2)//3)+1))


@pytest.mark.parametrize('raw',[
    'data:application/json;base64,'+base64.b64encode(b'\xff').decode(),
    'data:application/json,%FF', '['*2000+'0'+']'*2000,
])
def test_invalid_encoding_or_depth_has_share_error(raw):
    with pytest.raises(share.ShareError):share.load_share_input(raw)


def test_remote_invalid_encoding_has_share_error(monkeypatch):
    class Response:
        sent=False
        def getheader(self,name):return None
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read1(self,limit):
            assert 0<limit<=65536
            if self.sent:return b''
            self.sent=True
            return b'\xff'
    monkeypatch.setattr(share,'urlopen',lambda *a,**k:Response())
    with pytest.raises(share.ShareError,match='UTF-8'):
        share.load_share_input('https://raw.githubusercontent.com/example/repo/main/share.json')


def test_small_payload_all_local_encodings_work():
    payload={'schema':share.SCHEMA,'kind':'player_share','game':{'slug':'example'},'mods':[]}
    raw=json.dumps(payload)
    for value in [raw,share.make_offline_share_link(payload),'data:application/json,'+raw]:
        parsed,_=share.load_share_input(value)
        assert parsed==payload


@pytest.mark.parametrize('target',[
    'http://raw.githubusercontent.com/a/b', 'https://example.com/share',
    'https://127.0.0.1/share', 'https://raw.githubusercontent.com:8443/share',
    'https://user:private@raw.githubusercontent.com/share',
    'https://raw.githubusercontent.com:bad/share',
])
def test_remote_initial_and_redirect_urls_are_restricted(monkeypatch,target):
    from urllib.request import Request
    monkeypatch.setattr(share,'urlopen',lambda *a,**k:pytest.fail('Disallowed URL reached transport'))
    with pytest.raises(share.ShareError):share._read_remote_share(target)
    handler=share._ShareRedirectHandler()
    with pytest.raises(share.ShareError):
        handler.redirect_request(Request('https://raw.githubusercontent.com/a/b'),None,302,'Found',{},target)


def test_approved_redirect_still_supported():
    from urllib.request import Request
    result=share._ShareRedirectHandler().redirect_request(Request('https://raw.githubusercontent.com/a/b'),None,302,'Found',{},'https://gist.githubusercontent.com/a/raw/share.json')
    assert result.full_url=='https://gist.githubusercontent.com/a/raw/share.json'


def test_transport_error_does_not_leak_private_url(monkeypatch):
    def broken(*a,**k):raise OSError('private-token-path')
    monkeypatch.setattr(share,'urlopen',broken)
    with pytest.raises(share.ShareError) as error:share._read_remote_share('https://raw.githubusercontent.com/a/b')
    assert 'private-token' not in str(error.value)
    assert 'offline share' in str(error.value)
