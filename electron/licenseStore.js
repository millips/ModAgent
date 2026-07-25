const crypto = require('crypto')
const fs = require('fs')
const path = require('path')

const LICENSE_PREFIX = 'MAP1'
const PRODUCT_ID = 'modagent-p'
const TRIAL_DAYS = 3
const CLOCK_ROLLBACK_GRACE_MS = 6 * 60 * 60 * 1000
const DAY_MS = 24 * 60 * 60 * 1000

function atomicWriteJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  const temporary = `${filePath}.${process.pid}.tmp`
  fs.writeFileSync(temporary, JSON.stringify(value, null, 2), 'utf8')
  fs.renameSync(temporary, filePath)
}

function decodeToken(rawToken, publicKey) {
  const token = String(rawToken || '').replace(/\s+/g, '')
  const parts = token.split('.')
  if (parts.length !== 3 || parts[0] !== LICENSE_PREFIX) {
    throw new Error('兑换码格式不正确')
  }
  const [, encodedPayload, encodedSignature] = parts
  const signature = Buffer.from(encodedSignature, 'base64url')
  const verified = crypto.verify(
    null,
    Buffer.from(encodedPayload, 'utf8'),
    publicKey,
    signature,
  )
  if (!verified) throw new Error('兑换码签名无效')
  let payload
  try {
    payload = JSON.parse(Buffer.from(encodedPayload, 'base64url').toString('utf8'))
  } catch (_) {
    throw new Error('兑换码内容损坏')
  }
  if (payload.v !== 1 || payload.product !== PRODUCT_ID) {
    throw new Error('兑换码不适用于 ModAgent P')
  }
  if (!/^[A-Za-z0-9_-]{8,64}$/.test(String(payload.id || ''))) {
    throw new Error('兑换码编号无效')
  }
  const days = Number(payload.days)
  if (!Number.isInteger(days) || days < 1 || days > 366) {
    throw new Error('兑换码有效期无效')
  }
  return { token, payload: { ...payload, days } }
}

function createLicenseStore({
  dataDir,
  edition,
  safeStorage,
  publicKeyPath,
  logger = console,
  now = () => Date.now(),
}) {
  const licenseFile = path.join(dataDir, 'editions', 'subscription', 'license.dat')
  let publicKey = null

  function encryptionReady() {
    return Boolean(safeStorage?.isEncryptionAvailable?.())
  }

  function getPublicKey() {
    if (!publicKey) publicKey = fs.readFileSync(publicKeyPath, 'utf8')
    return publicKey
  }

  function encryptState(state) {
    if (!encryptionReady()) throw new Error('Windows 加密存储不可用')
    const encrypted = safeStorage.encryptString(JSON.stringify(state)).toString('base64')
    atomicWriteJson(licenseFile, { version: 1, protected: encrypted })
  }

  function decryptState() {
    if (!fs.existsSync(licenseFile)) return null
    if (!encryptionReady()) throw new Error('Windows 加密存储不可用')
    const envelope = JSON.parse(fs.readFileSync(licenseFile, 'utf8').replace(/^\uFEFF/, ''))
    if (envelope.version !== 1 || !envelope.protected) throw new Error('license.dat 格式无效')
    return JSON.parse(safeStorage.decryptString(Buffer.from(envelope.protected, 'base64')))
  }

  function initialState(timestamp) {
    return {
      version: 1,
      trial_started_at: timestamp,
      last_seen_at: timestamp,
      activations: {},
      current_token: '',
    }
  }

  function loadState({ create = true } = {}) {
    const timestamp = now()
    let state
    try {
      state = decryptState()
    } catch (error) {
      logger.error('Unable to read ModAgent P license state', error.message)
      return { error: '许可证文件无法读取，请检查系统加密存储或联系支持' }
    }
    if (!state && create) {
      state = initialState(timestamp)
      encryptState(state)
    }
    return { state }
  }

  function evaluateState(state, { touch = true } = {}) {
    const timestamp = now()
    const lastSeen = Number(state.last_seen_at || 0)
    if (lastSeen && timestamp + CLOCK_ROLLBACK_GRACE_MS < lastSeen) {
      return {
        edition: 'subscription',
        state: 'clock_error',
        entitled: false,
        message: '检测到系统时间明显回拨，请校准 Windows 时间后重试',
      }
    }

    if (touch && timestamp > lastSeen) {
      state.last_seen_at = timestamp
      encryptState(state)
    }

    if (state.current_token) {
      try {
        const { payload } = decodeToken(state.current_token, getPublicKey())
        const activation = state.activations?.[payload.id]
        const activatedAt = Number(activation?.activated_at || 0)
        const expiresAt = activatedAt + payload.days * DAY_MS
        if (activatedAt && timestamp < expiresAt) {
          return {
            edition: 'subscription',
            state: 'active',
            entitled: true,
            license_id: payload.id,
            duration_days: payload.days,
            activated_at: new Date(activatedAt).toISOString(),
            expires_at: new Date(expiresAt).toISOString(),
            days_remaining: Math.max(1, Math.ceil((expiresAt - timestamp) / DAY_MS)),
          }
        }
        if (activatedAt) {
          return {
            edition: 'subscription',
            state: 'expired',
            entitled: false,
            license_id: payload.id,
            expires_at: new Date(expiresAt).toISOString(),
            days_remaining: 0,
          }
        }
      } catch (error) {
        logger.error('Stored ModAgent P license is invalid', error.message)
        return {
          edition: 'subscription',
          state: 'invalid',
          entitled: false,
          message: '已保存的许可证无效，请重新输入兑换码',
        }
      }
    }

    const trialStartedAt = Number(state.trial_started_at || timestamp)
    const trialExpiresAt = trialStartedAt + TRIAL_DAYS * DAY_MS
    if (timestamp < trialExpiresAt) {
      return {
        edition: 'subscription',
        state: 'trial',
        entitled: true,
        trial: true,
        activated_at: new Date(trialStartedAt).toISOString(),
        expires_at: new Date(trialExpiresAt).toISOString(),
        days_remaining: Math.max(1, Math.ceil((trialExpiresAt - timestamp) / DAY_MS)),
      }
    }
    return {
      edition: 'subscription',
      state: 'trial_expired',
      entitled: false,
      trial: true,
      expires_at: new Date(trialExpiresAt).toISOString(),
      days_remaining: 0,
    }
  }

  function status() {
    if (edition !== 'subscription') {
      return { edition, state: 'not_applicable', entitled: false }
    }
    if (!encryptionReady()) {
      return {
        edition,
        state: 'unavailable',
        entitled: false,
        message: 'Windows 加密存储不可用，无法启用 P 会员',
      }
    }
    const loaded = loadState()
    if (loaded.error) {
      return { edition, state: 'invalid', entitled: false, message: loaded.error }
    }
    return evaluateState(loaded.state)
  }

  function activate(rawToken) {
    if (edition !== 'subscription') throw new Error('普通版不支持 P 会员兑换码')
    const { token, payload } = decodeToken(rawToken, getPublicKey())
    const loaded = loadState()
    if (loaded.error) throw new Error(loaded.error)
    const state = loaded.state
    const timestamp = now()
    const currentStatus = evaluateState(state, { touch: false })
    const existing = state.activations?.[payload.id]
    const activatedAt = existing?.activated_at
      ? Number(existing.activated_at)
      : Math.max(
          timestamp,
          currentStatus.state === 'active' ? Date.parse(currentStatus.expires_at) : timestamp,
        )
    state.activations = {
      ...(state.activations || {}),
      [payload.id]: {
        activated_at: activatedAt,
        duration_days: payload.days,
      },
    }
    state.current_token = token
    state.last_seen_at = Math.max(Number(state.last_seen_at || 0), timestamp)
    encryptState(state)
    return evaluateState(state, { touch: false })
  }

  return { status, activate, licenseFile }
}

module.exports = {
  createLicenseStore,
  decodeToken,
  LICENSE_PREFIX,
  PRODUCT_ID,
  TRIAL_DAYS,
  DAY_MS,
}
