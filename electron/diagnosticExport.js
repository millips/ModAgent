const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

function createDiagnosticExporter({ buildReport, preview, choosePath, io = fs }) {
  let busy = false;
  return async (language) => {
    if (busy) return { ok: false, error: 'DIAGNOSTICS_BUSY' };
    busy = true;
    let staging;
    try {
      const report = await buildReport();
      if (typeof report !== 'string' || !report.trim()) throw Error('empty report');
      if (!await preview(report, language)) return { ok: false, cancelled: true };
      const chosen = await choosePath(language);
      if (chosen.canceled || !chosen.filePath) return { ok: false, cancelled: true };
      if (path.extname(chosen.filePath).toLowerCase() !== '.txt') return { ok: false, error: 'DIAGNOSTICS_TEXT_REQUIRED' };
      staging = chosen.filePath + '.' + crypto.randomUUID() + '.tmp';
      await io.writeFile(staging, report, { encoding: 'utf8', flag: 'wx' });
      if (await io.readFile(staging, 'utf8') !== report) throw Error('verification failed');
      await io.rename(staging, chosen.filePath);
      staging = null;
      return { ok: true, filename: path.basename(chosen.filePath) };
    } catch (_) {
      // Never send filesystem paths or report content through error messages.
      return { ok: false, error: 'DIAGNOSTICS_EXPORT_FAILED' };
    } finally {
      if (staging) await io.unlink(staging).catch(() => {});
      busy = false;
    }
  };
}
module.exports = { createDiagnosticExporter };
