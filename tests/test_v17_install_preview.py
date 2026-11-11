import json
import os
import zipfile
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')

from modagent import installer


@pytest.mark.parametrize('slug,members', [
    ('palworld', {'wrapper/fixture.pak':b'pak'}),
    ('repo', {'BepInEx/plugins/Test/Test.dll':b'dll'}),
    ('local_final_fantasy_vii_rebirth', {
        'Package/Plugin/Plugin.uplugin':b'{}', 'Package/Plugin/Content/Test.pak':b'pak'}),
    ('stardewvalley', {'Auto/manifest.json':json.dumps({
        'Name':'Auto', 'Author':'Test', 'Version':'1.0',
        'UniqueID':'Test.Auto', 'EntryDll':'Auto.dll'}).encode(), 'Auto/Auto.dll':b'dll'}),
    ('skyrimspecialedition', {'fixture.esp':b'esp'}),
])
def test_preview_matches_commit_without_writes(tmp_path, monkeypatch, slug, members):
    game = tmp_path / 'game'; game.mkdir()
    (game / 'keep.txt').write_bytes(b'untouched')
    backup = tmp_path / 'backups'
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(backup))
    archive = tmp_path / 'fixture.zip'
    with zipfile.ZipFile(archive, 'w') as handle:
        for name, data in members.items():
            handle.writestr(name, data)
    preview = installer.preview_install(str(archive), str(game), slug)
    assert preview['planned_files']
    assert preview['installed'] == []
    assert list(game.iterdir()) == [game / 'keep.txt']
    assert not backup.exists()
    result = installer.install_mod(str(archive), str(game), slug)
    assert set(preview['planned_files']) == {item['dest'] for item in result['installed']}
    assert all(os.path.isfile(path) for path in preview['planned_files'])
    assert (game / 'keep.txt').read_bytes() == b'untouched'
