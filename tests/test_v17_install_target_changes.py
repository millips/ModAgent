import os
import zipfile
import pytest
if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')
from modagent import installer


@pytest.mark.parametrize('phase', ['staging', 'second_commit'])
def test_file_changes_during_transaction_are_preserved(monkeypatch, tmp_path, phase):
    root = tmp_path / 'game'; root.mkdir()
    first, second = root / 'a.txt', root / 'b.txt'
    first.write_bytes(b'old-a'); second.write_bytes(b'old-b')
    package = tmp_path / 'fixture.zip'
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('a.txt', b'new-a'); archive.writestr('b.txt', b'new-b')
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    real_copy, real_replace = installer.shutil.copy2, installer.os.replace
    mutations = []
    def mutate():
        second.write_bytes(b'user-change')
        mutations.append(1)
    def copy(source, target, *args, **kwargs):
        result = real_copy(source, target, *args, **kwargs)
        if phase == 'staging' and os.path.basename(os.path.dirname(target)) == 'stage' and not mutations:
            mutate()
        return result
    def replace(source, target):
        result = real_replace(source, target)
        if phase == 'second_commit' and os.path.basename(os.path.dirname(source)) == 'stage' and not mutations:
            mutate()
        return result
    monkeypatch.setattr(installer.shutil, 'copy2', copy)
    monkeypatch.setattr(installer.os, 'replace', replace)
    result = installer.install_mod_custom(str(package), str(root), 'fixture', {'a.txt':'a.txt', 'b.txt':'b.txt'})
    assert mutations
    assert not result['installed'] and result['errors'], result
    assert result['errors'][0]['error_code'] == 'INSTALL_TARGET_CHANGED'
    assert first.read_bytes() == b'old-a' and second.read_bytes() == b'user-change'
    assert not list(root.glob('.modagent-transaction-*'))


@pytest.mark.parametrize('external_action', ['edit', 'delete'])
@pytest.mark.parametrize('manifest_failure', [False, True])
def test_rollback_does_not_erase_changes_to_an_already_committed_file(monkeypatch, tmp_path, external_action, manifest_failure):
    if manifest_failure:
        import builtins
        real_open = builtins.open
        def guarded_open(path, mode='r', *args, **kwargs):
            if os.path.basename(os.fspath(path)) == 'recovery.json' and 'w' in mode:
                raise PermissionError('PRIVATE recovery manifest failure')
            return real_open(path, mode, *args, **kwargs)
        monkeypatch.setattr(builtins, 'open', guarded_open)
    root = tmp_path / 'game'; root.mkdir()
    first, second = root / 'a.txt', root / 'b.txt'
    first.write_bytes(b'old-a'); second.write_bytes(b'old-b')
    package = tmp_path / 'fixture.zip'
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('a.txt', b'new-a'); archive.writestr('b.txt', b'new-b')
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    real_replace = installer.os.replace
    def fail_second(source, target):
        if os.path.basename(os.path.dirname(source)) == 'stage' and str(target) == str(second):
            assert first.read_bytes() == b'new-a'
            if external_action == 'edit':
                first.write_bytes(b'user-edit-after-commit')
            else:
                first.unlink()
            raise PermissionError('PRIVATE second commit failure')
        return real_replace(source, target)
    monkeypatch.setattr(installer.os, 'replace', fail_second)
    result = installer.install_mod_custom(str(package), str(root), 'fixture', {'a.txt':'a.txt', 'b.txt':'b.txt'})
    assert not result['installed'] and result['errors']
    if external_action == 'edit':
        assert first.read_bytes() == b'user-edit-after-commit'
    else:
        assert not first.exists()
    assert second.read_bytes() == b'old-b'
    assert result['errors'][0]['error_code'] == 'INSTALL_ROLLBACK_INCOMPLETE'
    recovery = list(root.glob('.modagent-transaction-*'))
    assert len(recovery) == 1
    assert (recovery[0] / 'rollback' / '0').read_bytes() == b'old-a'
    assert result['errors'][0]['recovery_dir'] == str(recovery[0])
    import json
    mapping = [{'target': 'a.txt', 'original_backup': os.path.join('rollback', '0')}]
    assert result['errors'][0]['recovery_files'] == mapping
    assert result['errors'][0]['recovery_manifest_saved'] is (not manifest_failure)
    if manifest_failure:
        assert not (recovery[0] / 'recovery.json').exists()
    else:
        manifest = json.loads((recovery[0] / 'recovery.json').read_text(encoding='utf-8'))
        assert manifest['automatic_restore_complete'] is False
        assert manifest['originals'] == mapping
    assert 'PRIVATE' not in str(result)
