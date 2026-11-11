"""Backup identity belongs to a physical installation, not a catalogue game."""
from pathlib import Path
import pytest
from modagent import installer


@pytest.fixture
def roots(monkeypatch, tmp_path):
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    a, b = tmp_path / 'game-a', tmp_path / 'game-b'
    a.mkdir()
    b.mkdir()
    return a, b


def test_two_installations_restore_their_own_originals(roots):
    paths = [root / 'same.dll' for root in roots]
    for index, path in enumerate(paths):
        path.write_bytes(f'original-{index}'.encode())
        installer._backup_file(str(path), str(path.parent), 'same-game')
        path.write_bytes(b'modified')
    backups = [installer._backup_lookup(str(path), str(path.parent), 'same-game') for path in paths]
    assert backups[0] != backups[1]
    for index, path in enumerate(paths):
        result = installer.uninstall_mod('fixture', str(path.parent), [str(path)], 'same-game')
        assert result['status'] == 'completed'
        assert path.read_bytes() == f'original-{index}'.encode()


def test_unknown_legacy_backup_blocks_uninstall_and_is_preserved(roots):
    root, _ = roots
    path = root / 'same.dll'
    path.write_bytes(b'current-mod')
    legacy = Path(installer.BACKUPS_DIR) / 'same-game' / 'same.dll'
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b'could-belong-to-another-install')
    result = installer.uninstall_mod('fixture', str(root), [str(path)], 'same-game')
    assert result['status'] != 'completed'
    assert result['errors']
    assert path.read_bytes() == b'current-mod'
    assert legacy.read_bytes() == b'could-belong-to-another-install'


def test_unknown_legacy_backup_blocks_new_overwrite(roots):
    root, _ = roots
    path = root / 'same.dll'
    path.write_bytes(b'current')
    legacy = Path(installer.BACKUPS_DIR) / 'same-game' / 'same.dll'
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b'unknown-origin')
    with pytest.raises(RuntimeError, match='backup_ownership_unknown'):
        installer._backup_file(str(path), str(root), 'same-game')
    assert path.read_bytes() == b'current'


def test_backup_write_failure_is_not_silently_ignored(monkeypatch, roots):
    root, _ = roots
    path = root / 'same.dll'
    path.write_bytes(b'original')
    def failed(src, dest, *a, **kw):
        Path(dest).write_bytes(b'partial-copy')
        raise OSError('fixture backup disk full')
    monkeypatch.setattr(installer.shutil, 'copy2', failed)
    with pytest.raises(OSError, match='disk full'):
        installer._backup_file(str(path), str(root), 'same-game')
    assert not installer._backup_lookup(str(path), str(root), 'same-game')
    assert not list(Path(installer.BACKUPS_DIR).rglob('.backup-stage-*'))


def test_backup_target_cannot_escape_game_root(roots):
    root, other = roots
    path = other / 'precious.txt'
    path.write_bytes(b'precious')
    with pytest.raises(ValueError):
        installer._backup_file(str(path), str(root), 'same-game')
    assert path.read_bytes() == b'precious'


def test_same_installation_keeps_backup_when_catalogue_name_changes(roots):
    root, _ = roots
    path = root / 'same.dll'
    path.write_bytes(b'original')
    installer._backup_file(str(path), str(root), 'old-name')
    path.write_bytes(b'modified')
    result = installer.uninstall_mod('fixture', str(root), [str(path)], 'new-name')
    assert result['status'] == 'completed'
    assert path.read_bytes() == b'original'


def test_backup_failure_rolls_back_previous_install_destinations(monkeypatch, roots):
    root, source = roots
    operations = []
    for name in ('a.txt', 'b.txt'):
        (root / name).write_bytes(b'original-' + name.encode())
        (source / name).write_bytes(b'new-data')
        operations.append({'src': str(source / name), 'dest': str(root / name)})
    copy = installer.shutil.copy2
    def fail_second_backup(src, dest, *a, **kw):
        if str(src) == str(root / 'b.txt') and '.backup-stage-' in str(dest):
            raise OSError('fixture backup disk full')
        return copy(src, dest, *a, **kw)
    monkeypatch.setattr(installer.shutil, 'copy2', fail_second_backup)
    with pytest.raises(OSError, match='disk full'):
        installer._commit_files_transactionally(operations, str(root), 'same-game')
    assert (root / 'a.txt').read_bytes() == b'original-a.txt'
    assert (root / 'b.txt').read_bytes() == b'original-b.txt'
    assert not list(root.glob('.modagent-transaction-*'))


def test_legacy_install_bound_backup_remains_readable(roots):
    from modagent.config import make_game_instance_id
    root, _ = roots
    path = root / 'same.dll'
    path.write_bytes(b'modded')
    known = Path(installer.BACKUPS_DIR) / make_game_instance_id(str(root)) / 'same.dll'
    known.parent.mkdir(parents=True)
    known.write_bytes(b'original')
    result = installer.uninstall_mod('fixture', str(root), [str(path)], 'same-game')
    assert result['status'] == 'completed'
    assert path.read_bytes() == b'original'
