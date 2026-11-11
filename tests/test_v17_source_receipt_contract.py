"""Real binding receipts and persistence match renderer identity checks."""
import json
import os
from pathlib import Path
import subprocess
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('An isolated MODAGENT_DATA_DIR is required.')

from modagent import db, tools
from modagent.config import Config


@pytest.mark.parametrize('source', ['nexus', 'thunderstore'])
@pytest.mark.parametrize('instance', ['', 'fixture-instance-a'])
def test_binding_preview_and_confirm_match_renderer(monkeypatch, tmp_path, source, instance):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    cfg = Config(game_slug='fixture', game_instance_id=instance)
    scope = instance or 'fixture'
    db.add_mod(db.InstalledMod(id='local', name='Fixture', version='1', snapshot_id='', game_slug=scope))
    if instance:
        for other in ['fixture', 'fixture-instance-b']:
            db.add_mod(db.InstalledMod(id='local', name='Other installation', version='9', snapshot_id='', game_slug=other))
            db.upsert_mod_source_binding(other, 'local', 'nexus', '999', 'https://www.nexusmods.com/fixture/mods/999', 1.0, 'user_confirmed', '9', {})
    remote_slugs = []
    def detail(_id, slug, *args):
        remote_slugs.append(slug)
        return {'name':'Fixture','version':'2'}
    monkeypatch.setattr(tools.nexus, 'get_detail', detail)
    candidate = {'source':source, 'source_key':'123' if source=='nexus' else 'Team-Package',
                 'source_url':'https://www.nexusmods.com/fixture/mods/123' if source=='nexus'
                 else 'https://thunderstore.io/c/repo/p/Team/Package/'}
    args = {'local_mod_id':'local', **candidate}
    preview = tools.execute('mod_source_bind', {**args, 'confirmed':False}, cfg)
    assert json.loads(preview)['requires_confirmation'] is True
    assert json.loads(preview)['preview']['local']['name'] == 'Fixture'
    assert db.get_mod_source_binding('local', scope) is None
    bound = tools.execute('mod_source_bind', {**args, 'confirmed':True}, cfg)
    assert json.loads(bound)['bound'] is True
    record = db.get_mod_source_binding('local', scope)
    assert record['source'] == source and record['source_key'] == candidate['source_key']
    if instance:
        for other in ['fixture', 'fixture-instance-b']:
            assert db.get_mod_source_binding('local', other)['source_key'] == '999'
    assert remote_slugs == (['fixture', 'fixture'] if source == 'nexus' else [])
    script = '''
      import {validateSourceReceipt} from './electron/src/components/manualSource.mjs';
      let input='';for await(const chunk of process.stdin)input+=chunk;
      const data=JSON.parse(input);
      validateSourceReceipt({result:data.preview},'local',data.candidate,false);
      validateSourceReceipt({result:data.bound},'local',data.candidate,true);
      console.log('REAL_SOURCE_RECEIPTS_PASSED');
    '''
    checked = subprocess.run(['node','--input-type=module','-e',script],
        input=json.dumps({'preview':preview,'bound':bound,'candidate':candidate}),
        text=True,capture_output=True,timeout=20,cwd=Path(__file__).resolve().parents[1])
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert 'REAL_SOURCE_RECEIPTS_PASSED' in checked.stdout


@pytest.mark.parametrize('source', ['nexus', 'thunderstore'])
def test_missing_active_mod_cannot_bind_other_installation(monkeypatch, tmp_path, source):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    db.add_mod(db.InstalledMod(id='local', name='Other', version='1', snapshot_id='', game_slug='fixture'))
    cfg = Config(game_slug='fixture', game_instance_id='instance-without-mod')
    monkeypatch.setattr(tools.nexus, 'get_detail', lambda *a, **k: pytest.fail('Missing local Mod must not query source'))
    for confirmed in [False, True]:
        result = json.loads(tools.execute('mod_source_bind', {
            'local_mod_id':'local', 'source':source,
            'source_key':'123' if source=='nexus' else 'Team-Package',
            'source_url':'https://thunderstore.io/c/repo/p/Team/Package/',
            'confirmed':confirmed}, cfg))
        assert result.get('error') and not result.get('bound')
        assert db.get_mod_source_binding('local', 'fixture') is None
        assert db.get_mod_source_binding('local', 'instance-without-mod') is None


@pytest.mark.parametrize('source', ['nexus', 'thunderstore'])
@pytest.mark.parametrize('confirmed', ['false', 'true', 1, {'value': True}, [True], None, False])
def test_only_boolean_true_can_write_binding(monkeypatch, tmp_path, source, confirmed):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    cfg = Config(game_slug='fixture')
    db.add_mod(db.InstalledMod(id='local', name='Fixture', version='1', snapshot_id='', game_slug='fixture'))
    monkeypatch.setattr(tools.nexus, 'get_detail', lambda *a, **k: {'name':'Fixture','version':'2'})
    result = json.loads(tools.execute('mod_source_bind', {
        'local_mod_id':'local', 'source':source,
        'source_key':'123' if source=='nexus' else 'Team-Package',
        'source_url':'https://thunderstore.io/c/repo/p/Team/Package/',
        'confirmed':confirmed}, cfg))
    assert result.get('requires_confirmation') is True
    assert not result.get('bound')
    assert db.get_mod_source_binding('local', 'fixture') is None
