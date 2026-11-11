"""No Steam access: simulated subscription changes, real database and restore tool."""
import json
import os
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('An isolated MODAGENT_DATA_DIR is required.')

from modagent import db, tools, snapshot, user_config
from modagent.config import Config


@pytest.mark.parametrize('retry_ready',[True,False])
def test_workshop_cleanup_retry_after_remote_success(monkeypatch,tmp_path,retry_ready):
    monkeypatch.setattr(db,'DB_FILE',str(tmp_path/'state.db'))
    db.init_db()
    monkeypatch.setattr(snapshot,'SNAPSHOTS_DIR',str(tmp_path/'snapshots'))
    monkeypatch.setattr(snapshot,'_workshop_state',lambda *_:{'appid':'123','ids':['111']})
    monkeypatch.setattr(user_config,'capture_snapshot',lambda *a:{})
    monkeypatch.setattr(user_config,'preview_snapshot',lambda *a:{'action_count':0})
    monkeypatch.setattr(user_config,'restore_snapshot',lambda *a:{'complete':True})
    root=tmp_path/'game'; root.mkdir()
    (root/'fixture.txt').write_bytes(b'keep')
    db.add_custom_domain_files('fixture',['fixture.txt'])
    sid=snapshot.snapshot_create(str(root),'fixture')
    for mid in ['ws_111','ws_222']:
        db.add_mod(db.InstalledMod(id=mid,name=mid,version='',snapshot_id='',game_slug='fixture'))
    state={'extra':True,'calls':0}
    monkeypatch.setattr(snapshot,'_workshop_diff',lambda *a:(['222'] if state['extra'] else [],[]))
    def reconcile(*args):
        if not state['extra']:return {'appid':'123','in_sync':retry_ready,
            'manual_unsubscribe':[] if retry_ready else ['222']}
        state['extra']=False; state['calls']+=1
        return {'appid':'123','in_sync':False,'unsubscribed':['222'],
                'resubscribed':[],'manual_unsubscribe':[],'manual_subscribe':[]}
    monkeypatch.setattr(snapshot,'_reconcile_workshop',reconcile)
    original=db.remove_mod
    monkeypatch.setattr(db,'remove_mod',lambda *a: (_ for _ in ()).throw(RuntimeError('PRIVATE_FIXTURE')))
    cfg=Config(game_root=str(root),game_slug='fixture')
    def restore():
        preview=json.loads(tools.execute('snapshot_restore',{'snapshot_id':sid},cfg))
        return json.loads(tools.execute('snapshot_restore',{'snapshot_id':sid,'confirmed':True,
            'confirmation_token':preview['confirmation_token']},cfg))
    first=restore()
    assert not first['complete']
    assert first['inventory_cleanup']['failed_mod_ids']==['ws_222']
    assert db.get_mod('ws_222','fixture')
    assert 'PRIVATE_FIXTURE' not in json.dumps(first)
    monkeypatch.setattr(db,'remove_mod',original)
    retried=restore()
    assert retried['complete'] is retry_ready,retried
    assert bool(db.get_mod('ws_222','fixture')) is (not retry_ready)
    assert retried['inventory_cleanup']['failed_mod_ids']==([] if retry_ready else ['ws_222'])
    assert db.get_mod('ws_111','fixture')
    assert state['calls']==1


def test_pending_cleanup_is_scoped_and_latest_receipt_wins(monkeypatch,tmp_path):
    monkeypatch.setattr(db,'DB_FILE',str(tmp_path/'state.db'))
    db.init_db()
    receipt={'snapshot_id':'snapshot','game_instance_id':'game-a',
             'inventory_cleanup':{'complete':False,'failed_mod_ids':['ws_222']}}
    db.log_operation('snapshot_restore',receipt)
    db.log_operation('snapshot_restore',{**receipt,'game_instance_id':'game-b',
        'inventory_cleanup':{'complete':False,'failed_mod_ids':['ws_999']}})
    db.log_operation('snapshot_restore',{**receipt,'snapshot_id':'other',
        'inventory_cleanup':{'complete':True,'failed_mod_ids':[]}})
    assert db.pending_snapshot_inventory_cleanup('snapshot','game-a')==['ws_222']
    assert db.pending_snapshot_inventory_cleanup('snapshot','game-b')==['ws_999']
    assert db.pending_snapshot_inventory_cleanup('snapshot','unknown')==[]
    db.log_operation('snapshot_restore',{**receipt,'inventory_cleanup':{'complete':True,'failed_mod_ids':[]}})
    assert db.pending_snapshot_inventory_cleanup('snapshot','game-a')==[]
