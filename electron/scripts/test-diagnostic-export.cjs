const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createDiagnosticExporter } = require('../diagnosticExport');
(async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'modagent-diagnostic-export-'));
  const filePath = path.join(root, 'report.txt');
  const report = 'Fixture report\n中文诊断\n[REDACTED]';
  const options = {buildReport: () => report, preview: async value => {assert.equal(value, report); return true;}, choosePath: async () => ({filePath})};
  try {
    const save = createDiagnosticExporter(options);
    assert.deepEqual(await save('en'), {ok:true, filename:'report.txt'});
    assert.equal(await fs.readFile(filePath, 'utf8'), report);
    for (const stage of ['writeFile', 'readFile', 'rename']) {
      const failing = createDiagnosticExporter({...options, io:{...fs, [stage]:async () => {throw Error('secret diagnostic path');}}});
      assert.deepEqual(await failing('en'), {ok:false, error:'DIAGNOSTICS_EXPORT_FAILED'});
      assert.equal(await fs.readFile(filePath, 'utf8'), report);
      assert.deepEqual(await fs.readdir(root), ['report.txt']);
    }
    const corrupt = createDiagnosticExporter({...options, io:{...fs, readFile:async () => 'truncated'}});
    assert.equal((await corrupt()).error, 'DIAGNOSTICS_EXPORT_FAILED');
    assert.equal(await fs.readFile(filePath, 'utf8'), report);
    const cancelPreview = createDiagnosticExporter({...options, preview:async () => false, choosePath:async () => assert.fail('cancel must not show save')});
    assert.equal((await cancelPreview()).cancelled, true);
    const cancelSave = createDiagnosticExporter({...options, choosePath:async () => ({canceled:true})});
    assert.equal((await cancelSave()).cancelled, true);
    assert.equal((await createDiagnosticExporter({...options,choosePath:async () => ({filePath:path.join(root,'bad.exe')})})()).error,'DIAGNOSTICS_TEXT_REQUIRED');
    let release;
    const busy = createDiagnosticExporter({...options, preview:() => new Promise(resolve => {release = resolve;})});
    const pending = busy();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal((await busy()).error, 'DIAGNOSTICS_BUSY');
    release(false); await pending;
    const retry = busy();
    await new Promise(resolve => setImmediate(resolve));
    release(false); assert.equal((await retry).cancelled,true);
    assert.deepEqual(await fs.readdir(root), ['report.txt']);
    console.log('DIAGNOSTIC EXPORT PASSED: real UTF-8 save/readback, cancellation at both dialogs, write/read/replace faults preserve prior file, corruption rejected, cleanup, extension and duplicate guards');
  } finally {
    // Only this invocation's mkdtemp-created directory, never user diagnostics.
    await fs.rm(root, {recursive:true, force:true});
  }
})().catch(error => {console.error(error); process.exitCode=1;});
