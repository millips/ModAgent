"""Real public archive -> real file operations inside a temporary game only.

No downloaded executable is launched. This verifies placement/management, not
in-game compatibility and not an LLM-generated installation plan.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

root = Path(tempfile.mkdtemp(prefix='modagent-r5-live-install-'))
os.environ['MODAGENT_DATA_DIR'] = str(root / 'data')
from modagent import db, tools, installer
from modagent.sources import thunderstore

db.init_db()
game = root / 'MockREPO'
game.mkdir()
(game / 'REPO.exe').write_bytes(b'MODAGENT TEST SENTINEL - NOT EXECUTABLE')
(game / 'REPO_Data').mkdir()
cfg = SimpleNamespace(game_root=str(game), game_slug='repo', game_name='R.E.P.O.',
    game_id=0, nexus_api_key='', tier='free', chrome_cdp_port=0, agent_core_v2='on')
report = {'real_http': True, 'real_archive': True, 'game_is_fixture': True,
          'launched_downloaded_code': False, 'steps': [], 'workspace': str(root)}
output = Path(__file__).resolve().parents[1] / 'build/chain-reliability-r5/live-install-v3.json'
output.parent.mkdir(parents=True, exist_ok=True)

def save():
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

def call(name, args):
    value = json.loads(tools.execute(name, args, cfg))
    report['steps'].append({'tool': name, 'result': value})
    save()
    print(name + ': ' + str(value.get('status') or value.get('error') or 'returned'), flush=True)
    return value

try:
    # Install the real public prerequisite first, but only into the fake game.
    for owner, package in [('BepInEx', 'BepInExPack'), ('nickklmao', 'MenuLib'), ('dig', 'Minimap')]:
        url = f'https://thunderstore.io/c/repo/p/{owner}/{package}/'
        receipt = call('download_from_url', {'url': url})
        archive = receipt.get('local_path')
        if not archive or not Path(archive).is_file():
            raise RuntimeError('download_not_verified')
        report['steps'][-1]['archive_sha256'] = hashlib.sha256(Path(archive).read_bytes()).hexdigest()
        paths = call('conflict_check', {'local_path': archive})
        assert paths['incoming_files_count'] > 0
        installed = call('mod_install', {'mod_id': f'ts_{owner}_{package}', 'local_path': archive})
        if installed.get('compatibility_confirmation_required'):
            # This is a fixture-only opt-in after the real preflight has surfaced the risk.
            report['fixture_risk_accepted'] = True
            installed = call('mod_install', {'mod_id': f'ts_{owner}_{package}',
                'local_path': archive, 'compatibility_confirmed': True})
        if not installed.get('files_installed'):
            report['status'] = 'blocked_install_preflight'
            save()
            break
    else:
        rows = db.get_installed_mods('repo')
        target = next(row for row in rows if 'minimap' in row.name.casefold())
        tracked = json.loads(target.files_installed)
        before = {f: hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in tracked}
        disable_preview = call('mod_disable', {'mod_id': target.id})
        assert disable_preview.get('requires_confirmation')
        disabled = call('mod_disable', {'mod_id': target.id, 'confirmed': True,
            'confirmation_token': disable_preview['confirmation_token']})
        assert disabled['verified'] and all(Path(f + '.disabled').exists() for f in tracked)
        enabled = call('mod_enable', {'mod_id': target.id})
        if enabled.get('requires_confirmation'):
            enabled = call('mod_enable', {'mod_id': target.id, 'confirmed': True})
        assert not enabled.get('error') and all(hashlib.sha256(Path(f).read_bytes()).hexdigest() == h for f, h in before.items())
        report['management'] = {'disable': True, 'enable_preserved_hashes': True}
        preview = call('mod_uninstall', {'mod_id': target.id})
        assert preview.get('requires_confirmation') or preview.get('status') == 'confirmation_required'
        removed = call('mod_uninstall', {'mod_id': target.id, 'confirmed': True})
        assert all(not Path(f).exists() for f in tracked)
        assert db.get_mod(target.id, 'repo') is None
        report['status'] = 'passed_file_chain'
except Exception as exc:
    report['status'] = 'failed'
    report['error_type'] = type(exc).__name__
    report['error'] = str(exc)[:300]
finally:
    save()
print('FILE CHAIN: ' + report['status'], flush=True)
raise SystemExit(0 if report['status'] == 'passed_file_chain' else 1)
