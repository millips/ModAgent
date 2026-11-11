"""Diagnostic exports never overwrite a prior receipt or publish a partial zip."""
import os
from pathlib import Path
import zipfile
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('An isolated MODAGENT_DATA_DIR is required.')
from modagent import diagnostics


def test_same_second_exports_remain_distinct(monkeypatch, tmp_path):
    root = tmp_path / 'game'; root.mkdir()
    output = tmp_path / 'exports'
    monkeypatch.setattr(diagnostics.time, 'strftime', lambda *_: '20261014_120000')
    first = diagnostics.export_diag_bundle(str(root), 'fixture', out_dir=str(output))
    first_bytes = Path(first['bundle']).read_bytes()
    second = diagnostics.export_diag_bundle(str(root), 'fixture', operation_log=[{'new':'entry'}], out_dir=str(output))
    assert first['bundle'] != second['bundle']
    assert Path(first['bundle']).read_bytes() == first_bytes
    for result in [first, second]:
        with zipfile.ZipFile(result['bundle']) as archive:
            assert archive.testzip() is None
            assert set(archive.namelist()) == set(result['contains'])


@pytest.mark.parametrize('failure', ['write', 'publish'])
def test_failed_export_preserves_previous_and_does_not_publish_partial(monkeypatch, tmp_path, failure):
    root = tmp_path / 'game'; root.mkdir()
    output = tmp_path / 'exports'
    first = diagnostics.export_diag_bundle(str(root), 'fixture', out_dir=str(output))
    before = {p.name:p.read_bytes() for p in output.iterdir()}
    original_write = zipfile.ZipFile.writestr
    original_replace = os.replace
    def denied_write(self, name, *args, **kwargs):
        if name == 'operation_log.json': raise OSError('PRIVATE_FIXTURE')
        return original_write(self, name, *args, **kwargs)
    def denied_replace(*args, **kwargs): raise PermissionError('PRIVATE_FIXTURE')
    if failure == 'write': monkeypatch.setattr(zipfile.ZipFile, 'writestr', denied_write)
    else: monkeypatch.setattr(diagnostics.os, 'replace', denied_replace)
    result = diagnostics.export_diag_bundle(str(root), 'fixture', operation_log=[{}], out_dir=str(output))
    assert result.get('error_code') == 'DIAGNOSTIC_EXPORT_FAILED'
    assert not result.get('bundle') and not result.get('redacted')
    assert 'PRIVATE_FIXTURE' not in str(result)
    assert {p.name:p.read_bytes() for p in output.iterdir()} == before
    monkeypatch.setattr(zipfile.ZipFile, 'writestr', original_write)
    monkeypatch.setattr(diagnostics.os, 'replace', original_replace)
    retried = diagnostics.export_diag_bundle(str(root), 'fixture', operation_log=[{}], out_dir=str(output))
    assert retried.get('bundle') and retried['bundle'] != first['bundle']
