const fs = require('fs');
const path = require('path');

const SECRET_KEY_PATTERN = '(?:api[_-]?key|token|authorization|secret|password|cookie)';

function redactDiagnosticText(input) {
  let text = String(input || '');
  text = text.replace(/\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi, 'Bearer [REDACTED]');
  text = text.replace(
    new RegExp(`("?${SECRET_KEY_PATTERN}"?\\s*[:=]\\s*)("[^"\\r\\n]*"|[^\\s,;]+)`, 'gi'),
    '$1"[REDACTED]"',
  );
  text = text.replace(/\b(?:sk|tvly|nxs)_[A-Za-z0-9_-]{12,}\b/g, '[REDACTED]');
  text = text.replace(/([?&](?:key|token|api_key|access_token)=)[^&\s]+/gi, '$1[REDACTED]');
  return text;
}

function buildDiagnosticReport({ diagnostics, productName, version, edition }) {
  const sections = [
    `${productName} ${version}`,
    `Generated: ${new Date().toISOString()}`,
    `Edition: ${edition}`,
  ];
  for (const filename of ['desktop.log', 'updater.log']) {
    const filePath = path.join(diagnostics.logsDir, filename);
    if (fs.existsSync(filePath)) {
      sections.push(`\n===== ${filename} =====\n${fs.readFileSync(filePath, 'utf8').slice(-500000)}`);
    }
  }
  if (fs.existsSync(diagnostics.stateFile)) {
    sections.push(`\n===== runtime-state.json =====\n${fs.readFileSync(diagnostics.stateFile, 'utf8')}`);
  }
  return redactDiagnosticText(sections.join('\n'));
}

function atomicWriteJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tempPath = `${filePath}.${process.pid}.tmp`;
  fs.writeFileSync(tempPath, JSON.stringify(value, null, 2), 'utf8');
  fs.renameSync(tempPath, filePath);
}

function createRuntimeDiagnostics({ dataDir, edition, productName, version }) {
  const baseDir = path.join(dataDir, 'editions', edition);
  const logsDir = path.join(baseDir, 'logs');
  const updatesDir = path.join(baseDir, 'updates');
  const stateFile = path.join(baseDir, 'runtime-state.json');
  const logFile = path.join(logsDir, 'desktop.log');
  fs.mkdirSync(logsDir, { recursive: true });
  fs.mkdirSync(updatesDir, { recursive: true });

  function rotateLog() {
    try {
      if (!fs.existsSync(logFile) || fs.statSync(logFile).size < 2 * 1024 * 1024) return;
      for (let i = 2; i >= 1; i -= 1) {
        const src = i === 1 ? logFile : `${logFile}.${i - 1}`;
        const dest = `${logFile}.${i}`;
        if (fs.existsSync(src)) fs.copyFileSync(src, dest);
      }
      fs.writeFileSync(logFile, '', 'utf8');
    } catch (_) {}
  }

  function write(level, ...parts) {
    rotateLog();
    const text = parts.map(part => {
      if (part instanceof Error) return part.stack || part.message;
      if (typeof part === 'string') return part;
      try { return JSON.stringify(part); } catch (_) { return String(part); }
    }).join(' ');
    fs.appendFileSync(logFile, `${new Date().toISOString()} [${level}] ${text}\n`, 'utf8');
  }

  const logger = {
    info: (...parts) => write('INFO', ...parts),
    warn: (...parts) => write('WARN', ...parts),
    error: (...parts) => write('ERROR', ...parts),
  };

  function readState() {
    try {
      return JSON.parse(fs.readFileSync(stateFile, 'utf8'));
    } catch (_) {
      return {};
    }
  }

  function writeState(state) {
    atomicWriteJson(stateFile, state);
  }

  function beginLaunch() {
    const state = readState();
    const previousFailed = state.pendingVersion && !state.lastExitClean && !state.healthy;
    const failures = previousFailed ? (Number(state.failures) || 0) + 1 : 0;
    const next = {
      ...state,
      productName,
      edition,
      pendingVersion: version,
      healthy: false,
      lastExitClean: false,
      failures,
      launchedAt: new Date().toISOString(),
    };
    writeState(next);
    logger.info('Application launch', { version, failures, previousFailed: Boolean(previousFailed) });
    return {
      failures,
      shouldOfferRollback: failures >= 2 && Boolean(state.lastGoodInstaller) && fs.existsSync(state.lastGoodInstaller),
      lastGoodInstaller: state.lastGoodInstaller || '',
      previousVersion: state.lastGoodVersion || '',
    };
  }

  function markHealthy() {
    const state = readState();
    const candidate = state.downloadedCandidate;
    if (candidate && candidate.version === version && fs.existsSync(candidate.installer || '')) {
      state.lastGoodInstaller = candidate.installer;
      state.lastGoodVersion = version;
      delete state.downloadedCandidate;
    } else if (!state.lastGoodVersion) {
      state.lastGoodVersion = version;
    }
    state.healthy = true;
    state.failures = 0;
    state.healthyAt = new Date().toISOString();
    writeState(state);
    logger.info('Application marked healthy', { version });
  }

  function markCleanExit() {
    const state = readState();
    state.lastExitClean = true;
    state.exitedAt = new Date().toISOString();
    writeState(state);
  }

  function recordDownloadedInstaller(sourcePath, targetVersion) {
    if (!sourcePath || !fs.existsSync(sourcePath)) return '';
    const safeVersion = String(targetVersion || 'unknown').replace(/[^0-9A-Za-z._-]/g, '_');
    const target = path.join(updatesDir, `${safeVersion}.exe`);
    fs.copyFileSync(sourcePath, target);
    const state = readState();
    state.downloadedCandidate = { version: String(targetVersion || ''), installer: target };
    writeState(state);
    logger.info('Cached update installer', { targetVersion, target });
    return target;
  }

  process.on('uncaughtException', error => logger.error('uncaughtException', error));
  process.on('unhandledRejection', error => logger.error('unhandledRejection', error));

  return {
    logger, logsDir, updatesDir, logFile, stateFile,
    beginLaunch, markHealthy, markCleanExit, recordDownloadedInstaller,
  };
}

module.exports = { createRuntimeDiagnostics, redactDiagnosticText, buildDiagnosticReport };
