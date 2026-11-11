"""Two isolated users share a manifest without installing or changing files."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Set MODAGENT_DATA_DIR to a fresh isolated test directory first.')

from modagent import db, tools, share_config
from modagent.config import Config


@pytest.mark.parametrize('friend_has_mod', [False, True])
@pytest.mark.parametrize('friend_version', ['1', '2', ''])
def test_friend_share_roundtrip_matches_renderer(monkeypatch, tmp_path, friend_has_mod, friend_version):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    author_root = tmp_path / 'author-game'
    friend_root = tmp_path / 'friend-game'
    author_root.mkdir(); friend_root.mkdir()
    author_file = author_root / 'private-fixture.dll'
    friend_file = friend_root / 'save.txt'
    author_file.write_bytes(b'author content')
    friend_file.write_bytes(b'friend save')
    author = Config(game_slug='example-game', game_instance_id='author-instance',
        game_root=str(author_root), nexus_api_key='secret-fixture-key', llm_api_key='secret-fixture-key')
    friend = Config(game_slug='example-game', game_instance_id='friend-instance', game_root=str(friend_root))
    db.add_mod(db.InstalledMod(id='a',name='Shared mod',version='1',snapshot_id='',
        game_slug='author-instance',files_installed=json.dumps([str(author_file)])))
    db.add_mod(db.InstalledMod(id='unresolved',name='Local-only mod',version='1',snapshot_id='',game_slug='author-instance'))
    db.upsert_mod_source_binding('author-instance','a','github','fixture/shared',
        'https://github.com/fixture/shared/releases',confidence=0.99)
    if friend_has_mod:
        db.add_mod(db.InstalledMod(id='different-local-id',name='Existing friend mod',version=friend_version,snapshot_id='',game_slug='friend-instance'))
        db.upsert_mod_source_binding('friend-instance','different-local-id','github','fixture/shared',
            'https://github.com/fixture/shared/releases',confidence=0.99)
    before_ids = [m.id for m in db.get_installed_mods('friend-instance')]
    exported = json.loads(tools.execute('share_export', {}, author))
    for forbidden in ['secret-fixture-key',str(author_root),str(author_file)]:
        assert forbidden not in exported['share_json']
    previews=[]
    for raw in [exported['share_json'],exported['offline_share_link']]:
        preview=json.loads(tools.execute('share_import',{'share':raw},friend))
        assert preview['safe_to_auto_install'] is False
        assert preview['summary']['total']==2
        assert preview['summary']['needs_source_resolution']==1
        assert preview['summary']['already_installed']==int(friend_has_mod)
        assert preview['summary']['needs_verification']==int(not friend_has_mod)
        previews.append(preview)
    def unavailable(_url):
        raise share_config.ShareError('fixture remote unavailable')
    monkeypatch.setattr(share_config,'_read_remote_share',unavailable)
    failed=json.loads(tools.execute('share_import',{'share':'https://raw.githubusercontent.com/fixture/shared/main/share.json'},friend))
    assert failed['error'] and failed['safe_to_auto_install'] is False
    assert [m.id for m in db.get_installed_mods('friend-instance')]==before_ids
    assert list(friend_root.iterdir())==[friend_file]
    assert friend_file.read_bytes()==b'friend save'
    assert author_file.read_bytes()==b'author content'
    script="""
import assert from 'node:assert/strict';
import {validateSharePreview,validateShareExport,readShareResult,installedShareVersionLabel} from './electron/src/components/shareResponse.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;
const data=JSON.parse(raw);validateShareExport(data.exported,2);
for(const preview of data.previews)validateSharePreview(readShareResult({result:JSON.stringify(preview)}));
for(const item of data.previews[0].items.filter(x=>x.status==='already_installed')){
  const label=installedShareVersionLabel(item,'en');
  assert.ok(label.includes(!data.friend_version?'unavailable':data.friend_version==='1'?'recorded version matches':'Version differs'));
}
assert.throws(()=>readShareResult({result:JSON.stringify(data.failed)}),/SHARE_VERIFICATION_REJECTED/);
console.log('REAL FRIEND SHARE CONTRACT PASSED');
"""
    node=shutil.which('node')
    assert node, 'Node is required for renderer contract verification'
    result=subprocess.run([node,'--input-type=module','-e',script],
        input=json.dumps({'exported':exported,'previews':previews,'failed':failed,'friend_version':friend_version}),text=True,
        capture_output=True,cwd=Path(__file__).resolve().parents[1],timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'REAL FRIEND SHARE CONTRACT PASSED' in result.stdout


@pytest.mark.parametrize('layout,expected', [('active','enabled_files'),('disabled','disabled_files'),('both','unknown'),('missing','unknown'),('mixed','unknown'),('workshop','unknown')])
def test_observed_file_state_is_conservative(tmp_path, layout, expected):
    path=tmp_path/'fixture.dll'
    files=[str(path)]
    if layout in ('active','both','mixed','workshop'):path.write_bytes(b'active')
    if layout in ('disabled','both'):Path(str(path)+'.disabled').write_bytes(b'disabled')
    if layout=='mixed':
        other=tmp_path/'other.dll'
        Path(str(other)+'.disabled').write_bytes(b'disabled')
        files.append(str(other))
    mod=db.InstalledMod(id='fixture',name='Fixture',version='1',snapshot_id='',files_installed=json.dumps(files),installed_by='steam_workshop' if layout=='workshop' else 'modagent')
    assert share_config._file_state(mod)==expected


@pytest.mark.parametrize('field,value', [
    ('name',{'text':'A'}),('enabled','false'),('enabled',0),('load_order','2'),
    ('load_order',True),('load_order',1.5),('load_order',2**54),
    ('dependencies','library'),('dependencies',[{}]),('source',[]),
    ('source',{'type':{}}),('source',{'key':1}),('warnings','text'),
    ('warnings',[{}]),('version',{}),('file_state',True),
])
def test_malformed_share_fields_rejected_before_preview(monkeypatch, tmp_path, field, value):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    payload={'schema':share_config.SCHEMA,'kind':'player_share','game':{'slug':'fixture'},
        'mods':[{'name':'A',field:value}]}
    result=json.loads(tools.execute('share_import',{'share':json.dumps(payload)},
        Config(game_root=str(tmp_path),game_slug='fixture')))
    assert result.get('kind')=='share_import_error', result
    assert result.get('safe_to_auto_install') is False
    assert 'items' not in result
