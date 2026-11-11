"""Share -> server plan -> HTTP grant -> real local I/O; scripted model substitute.

This does not verify source lookup, model planning, or the production install tool.
"""
import io
import json
import os
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('An isolated MODAGENT_DATA_DIR is required.')

from modagent import api, db, tools, downloader, installer
from modagent.config import Config
from modagent.orchestration.models import AgentMode, TaskSpec
from modagent.orchestration.runtime import AgentCoreRuntime
from modagent.orchestration import store


@pytest.mark.parametrize('corrupt', [False, True])
def test_share_requires_server_confirmation_before_local_io(monkeypatch, tmp_path, corrupt):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    author_root = tmp_path / 'author'
    friend_root = tmp_path / 'friend'
    author_root.mkdir(); friend_root.mkdir()
    (friend_root / 'plugin.txt').write_bytes(b'original')
    (friend_root / 'save.txt').write_bytes(b'user-save')
    author = Config(game_root=str(author_root),game_slug='fixture',game_instance_id='author')
    friend = Config(game_root=str(friend_root),game_slug='fixture',game_instance_id='friend',agent_core_v2='on')
    db.add_mod(db.InstalledMod(id='author-mod',name='Shared fixture',version='1',
        snapshot_id='',game_slug='author'))
    db.upsert_mod_source_binding('author','author-mod','github','fixture/shared',
        'https://github.com/fixture/shared',confidence=0.99)
    exported = json.loads(tools.execute('share_export',{},author))
    preview = json.loads(tools.execute('share_import',{'share':exported['share_json']},friend))
    assert preview['safe_to_auto_install'] is False
    assert preview['items'][0]['status'] == 'ready_for_source_verification'
    assert not db.get_installed_mods('friend')
    assert (friend_root / 'plugin.txt').read_bytes() == b'original'
    archive = io.BytesIO()
    with zipfile.ZipFile(archive,'w') as package:
        package.writestr('plugin.txt',b'new-plugin')
    payload = b'corrupt-package' if corrupt else archive.getvalue()
    hits = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker = threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    monkeypatch.setattr(api,'cfg',friend)
    monkeypatch.setattr(api,'_API_TOKEN','fixture-token')
    monkeypatch.setattr(api,'_chat_tasks',{})
    monkeypatch.setattr(api,'agents',{})
    monkeypatch.setattr(installer,'BACKUPS_DIR',str(tmp_path/'backups'))
    db.create_session('friend-session','fixture','friend')
    key = 'github:' + preview['items'][0]['source']['key']
    target = {'selection_key':key,'source':'github','source_id':'fixture/shared',
        'canonical_tool_mod_id':key,'name':preview['items'][0]['name'],'installable':True,
        'download_url':f'http://127.0.0.1:{server.server_port}/fixture.zip'}
    # Explicit synthetic source verification/plan, not inferred trust in the share.
    spec = TaskSpec.create(session_id='friend-session',game_id='friend',
        intent=AgentMode.BUILD_PLAN,user_goal='Fixture verified plan',targets=[target])
    runtime = AgentCoreRuntime(spec,feature_mode='on')
    runtime.start()
    runtime.record_plan_revision({'items':[target],'selected_keys':[key]})
    runtime.finalize_from_text('fixture ready',waiting_confirmation=True)
    revision = store.get_plan_revision(spec.task_id)
    observed = []
    class ScriptedExecutor:
        def __init__(self,cfg): self.history=[]
        def chat_stream(self,message,**kwargs):
            granted = kwargs['task_spec']
            assert granted.authorization['install'] is True
            assert granted.constraints['execution_grant_id'].startswith('grant_')
            selected = kwargs['recommendation_selection'][0]
            assert selected['name'] == 'Shared fixture'
            assert selected['download_url'] == target['download_url']
            downloaded = tmp_path/'fixture.zip'
            downloader.download_file(selected['download_url'],str(downloaded))
            assert downloaded.read_bytes() == payload
            try:
                result = installer.install_mod_custom(str(downloaded),str(friend_root),
                    'fixture',{'plugin.txt':'plugin.txt'})
                observed.append(result)
            except RuntimeError as exc:
                observed.append({'error':str(exc)})
            self.history=[{'role':'user','content':message}]
            yield json.dumps({'chunk':'fixture executor finished'})
            yield json.dumps({'done':True})
    monkeypatch.setattr(api,'Agent',ScriptedExecutor)
    client=TestClient(api.app,headers={'X-ModAgent-Token':'fixture-token'})
    try:
        body={'session_id':'friend-session','message':'Confirm installation',
            'selection_action':'confirm','recommendation_selection':[target]}
        assert client.post('/chat/stream',json=body).status_code == 409
        body.update(plan_task_id=spec.task_id,plan_revision_id=revision.revision_id)
        bad={**body,'recommendation_selection':[{**target,'selection_key':'github:other/repo'}]}
        assert client.post('/chat/stream',json=bad).status_code == 409
        assert not hits and not observed
        assert (friend_root/'plugin.txt').read_bytes() == b'original'
        # Server metadata must win over client-supplied names and download URLs.
        body['recommendation_selection']=[{**target,'name':'tampered','download_url':'https://invalid.example/private'}]
        assert client.post('/chat/stream',json=body).status_code == 200
        assert len(observed) == 1
        assert hits == ['/fixture.zip']
        replay=client.post('/chat/stream',json=body)
        assert replay.status_code == 409
        assert hits == ['/fixture.zip']
        if corrupt:
            assert observed[0].get('error')
            assert (friend_root/'plugin.txt').read_bytes() == b'original'
        else:
            assert len(observed[0]['installed']) == 1
            assert not observed[0]['errors']
            assert (friend_root/'plugin.txt').read_bytes() == b'new-plugin'
            backup=installer._backup_lookup(str(friend_root/'plugin.txt'),str(friend_root),'fixture')
            with open(backup,'rb') as handle: assert handle.read() == b'original'
        assert (friend_root/'save.txt').read_bytes() == b'user-save'
        assert not list(friend_root.glob('.modagent-transaction-*'))
    finally:
        client.close()
        server.shutdown(); server.server_close(); worker.join(2)
