"""Production tool preflight, snapshot, file commit and inventory consistency."""
import json
import os
import zipfile

import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('An isolated MODAGENT_DATA_DIR is required.')

from modagent import db, tools, snapshot, installer, user_config
from modagent.config import Config


@pytest.mark.parametrize('fault', ['none','inventory','write','legacy'])
def test_confirmed_install_tool_and_inventory_are_consistent(monkeypatch,tmp_path,fault):
    monkeypatch.setattr(db,'DB_FILE',str(tmp_path/'state.db'))
    db.init_db()
    monkeypatch.setattr(snapshot,'SNAPSHOTS_DIR',str(tmp_path/'snapshots'))
    monkeypatch.setattr(installer,'BACKUPS_DIR',str(tmp_path/'backups'))
    monkeypatch.setattr(snapshot,'_workshop_state',lambda *_:None)
    monkeypatch.setattr(user_config,'capture_snapshot',lambda *a:{})
    monkeypatch.setattr(user_config,'preview_snapshot',lambda *a:{'action_count':0})
    monkeypatch.setattr(user_config,'restore_snapshot',lambda *a:{'complete':True})
    root=tmp_path/'game'
    exe=root/'Pal'/'Binaries'/'Win64'/'Palworld-Win64-Shipping.exe'
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'fixture executable marker')
    relative='Pal/Content/Localization/Game/fixture.locres'
    destination=root/relative
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b'original')
    save=root/'user-save.txt'
    save.write_bytes(b'keep')
    package=tmp_path/'fixture.zip'
    with zipfile.ZipFile(package,'w') as archive:
        archive.writestr('fixture.locres',b'replacement')
    cfg=Config(game_root=str(root),game_slug='palworld',game_name='Palworld')
    args={'local_path':str(package),'mapping':{'fixture.locres':relative},
          'require_verified_preflight':True}
    preview=json.loads(tools.execute('mod_install_custom',args,cfg))
    assert preview['status']=='preinstall_confirmation_required',preview
    assert destination.read_bytes()==b'original'
    assert not db.get_installed_mods('palworld')
    assert not db.list_snapshots('palworld')
    denied=json.loads(tools.execute('mod_install_custom',{**args,'preflight_confirmed':True},cfg))
    assert denied['status']=='preinstall_confirmation_invalid',denied
    assert destination.read_bytes()==b'original'
    if fault=='inventory':
        def denied_registration(_mod): raise RuntimeError('fixture inventory failure')
        monkeypatch.setattr(db,'add_mod',denied_registration)
    if fault=='write':
        original_replace=installer.os.replace
        def denied_replace(source,target):
            if os.path.basename(os.path.dirname(source))=='stage':
                raise PermissionError('fixture write failure')
            return original_replace(source,target)
        monkeypatch.setattr(installer.os,'replace',denied_replace)
    result=json.loads(tools.execute('mod_install_custom',{**args,'preflight_confirmed':True,
        'preflight_confirmation_token':preview['confirmation_token']},cfg))
    if fault in ('none','legacy'):
        assert result['installed']==1,result
        assert destination.read_bytes()==b'replacement'
        rows=db.get_installed_mods('palworld')
        assert len(rows)==1
        assert json.loads(rows[0].files_installed)==[str(destination)]
        assert rows[0].snapshot_id==result['snapshot_id']
        assert relative in db.get_custom_domain_files('palworld')
        if fault=='legacy':
            manifest_path=tmp_path/'snapshots'/'palworld'/result['snapshot_id']/'manifest.json'
            manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest.pop('inventory_mod_ids')
            manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
        rollback_preview=json.loads(tools.execute('snapshot_restore',{'snapshot_id':result['snapshot_id']},cfg))
        restored=json.loads(tools.execute('snapshot_restore',{'snapshot_id':result['snapshot_id'],
            'confirmed':True,'confirmation_token':rollback_preview['confirmation_token']},cfg))
        assert restored['complete'],restored
    else:
        assert result.get('error'),result
        assert not result.get('installed')
        if fault=='inventory':assert result['rollback_complete'],result
    assert destination.read_bytes()==b'original'
    assert len(db.get_installed_mods('palworld')) == int(fault=='legacy')
    assert save.read_bytes()==b'keep'
    assert not list(root.glob('.modagent-transaction-*'))


@pytest.mark.parametrize('case',['identical','mixed','partial','existing','outside','other_snapshot','cleanup','audit'])
def test_rollback_inventory_boundaries(monkeypatch,tmp_path,case):
    monkeypatch.setattr(db,'DB_FILE',str(tmp_path/'state.db'))
    db.init_db()
    monkeypatch.setattr(snapshot,'SNAPSHOTS_DIR',str(tmp_path/'snapshots'))
    monkeypatch.setattr(snapshot,'_workshop_state',lambda *_:None)
    monkeypatch.setattr(user_config,'capture_snapshot',lambda *a:{})
    monkeypatch.setattr(user_config,'preview_snapshot',lambda *a:{'action_count':0})
    monkeypatch.setattr(user_config,'restore_snapshot',lambda *a:{'complete':True})
    root=tmp_path/'game'
    root.mkdir()
    paths=[root/'a.txt',root/'b.txt']
    for path in paths:path.write_bytes(b'original')
    db.add_custom_domain_files('fixture',['a.txt','b.txt'])
    if case=='existing':
        db.add_mod(db.InstalledMod(id='tested',name='Already installed',version='1',snapshot_id='',
            game_slug='fixture',files_installed=json.dumps([str(p) for p in paths])))
    sid=snapshot.snapshot_create(str(root),'fixture',trigger_mod_name='boundary')
    if case=='existing':
        # Even a row referencing this snapshot must survive if in its baseline.
        db.add_mod(db.InstalledMod(id='tested',name='Already installed',version='1',snapshot_id=sid,
            game_slug='fixture',files_installed=json.dumps([str(p) for p in paths])))
    tracked=list(paths)
    if case=='outside':
        outside=tmp_path/'outside.txt'
        outside.write_bytes(b'keep-outside')
        tracked.append(outside)
    if case!='existing':
        db.add_mod(db.InstalledMod(id='tested',name='New install',version='1',
            snapshot_id=sid if case!='other_snapshot' else 'different-snapshot',
            game_slug='fixture',files_installed=json.dumps([str(p) for p in tracked])))
    if case!='identical':paths[0].write_bytes(b'changed')
    if case=='partial':
        paths[1].write_bytes(b'changed')
        copy=snapshot.shutil.copy2
        def fail_second(src,dst,*args,**kwargs):
            if os.path.normcase(os.path.abspath(dst))==os.path.normcase(str(paths[1])):
                raise PermissionError('fixture rollback failure')
            return copy(src,dst,*args,**kwargs)
        monkeypatch.setattr(snapshot.shutil,'copy2',fail_second)
    cfg=Config(game_root=str(root),game_slug='fixture')
    preview=json.loads(tools.execute('snapshot_restore',{'snapshot_id':sid},cfg))
    original_remove=db.remove_mod
    original_log=db.log_operation
    if case=='audit':
        def failed_log(*args,**kwargs):raise RuntimeError('PRIVATE_FIXTURE audit failure')
        monkeypatch.setattr(db,'log_operation',failed_log)
    if case=='cleanup':
        def failed_remove(*args,**kwargs):raise RuntimeError('PRIVATE_FIXTURE inventory locked')
        monkeypatch.setattr(db,'remove_mod',failed_remove)
    restored=json.loads(tools.execute('snapshot_restore',{'snapshot_id':sid,'confirmed':True,
        'confirmation_token':preview['confirmation_token']},cfg))
    assert restored['complete'] is (case not in ('partial','cleanup','audit'))
    assert bool(db.get_mod('tested','fixture')) is (case not in ('identical','mixed','audit'))
    assert paths[0].read_bytes()==b'original'
    assert paths[1].read_bytes()==(b'changed' if case=='partial' else b'original')
    if case=='outside':assert outside.read_bytes()==b'keep-outside'
    if case=='audit':
        assert restored['audit_log_saved'] is False
        assert restored['restore_verified'] is True
        assert 'PRIVATE_FIXTURE' not in json.dumps(restored)
        monkeypatch.setattr(db,'log_operation',original_log)
        preview2=json.loads(tools.execute('snapshot_restore',{'snapshot_id':sid},cfg))
        retry=json.loads(tools.execute('snapshot_restore',{'snapshot_id':sid,'confirmed':True,
            'confirmation_token':preview2['confirmation_token']},cfg))
        assert retry['complete'] and retry['audit_log_saved']
        assert all(path.read_bytes()==b'original' for path in paths)
    if case=='cleanup':
        assert restored['inventory_cleanup']['complete'] is False
        assert restored['inventory_cleanup']['failed_mod_ids']==['tested']
        assert 'PRIVATE_FIXTURE' not in json.dumps(restored)
        monkeypatch.setattr(db,'remove_mod',original_remove)
        retry_preview=json.loads(tools.execute('snapshot_restore',{'snapshot_id':sid},cfg))
        retried=json.loads(tools.execute('snapshot_restore',{'snapshot_id':sid,'confirmed':True,
            'confirmation_token':retry_preview['confirmation_token']},cfg))
        assert retried['complete'],retried
        assert not db.get_mod('tested','fixture')
        assert all(path.read_bytes()==b'original' for path in paths)


def test_inventory_change_prevents_snapshot_reuse(monkeypatch,tmp_path):
    monkeypatch.setattr(db,'DB_FILE',str(tmp_path/'state.db'))
    db.init_db()
    monkeypatch.setattr(snapshot,'SNAPSHOTS_DIR',str(tmp_path/'snapshots'))
    monkeypatch.setattr(snapshot,'_workshop_state',lambda *_:None)
    monkeypatch.setattr(user_config,'capture_snapshot',lambda *a:{})
    root=tmp_path/'game'
    root.mkdir()
    file=root/'a.txt'
    file.write_bytes(b'unchanged')
    db.add_custom_domain_files('fixture',['a.txt'])
    first=snapshot.snapshot_create(str(root),'fixture',trigger_mod_name='same-trigger')
    assert snapshot.snapshot_create(str(root),'fixture',trigger_mod_name='same-trigger')==first
    db.add_mod(db.InstalledMod(id='new',name='New record',version='1',snapshot_id=first,
        game_slug='fixture',files_installed=json.dumps([str(file)])))
    second=snapshot.snapshot_create(str(root),'fixture',trigger_mod_name='same-trigger')
    assert second!=first
    manifest=json.loads((tmp_path/'snapshots'/'fixture'/second/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['inventory_mod_ids']==['new']
    assert file.read_bytes()==b'unchanged'
