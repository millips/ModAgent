import { useEffect, useState } from 'react'

export const P_LICENSE_EVENT = 'modagent:p-license-status'

const NOT_APPLICABLE = {
  edition: 'free',
  state: 'not_applicable',
  entitled: false,
}

export function readPLicenseStatus() {
  if (!__MODAGENT_SUBSCRIPTION__) return NOT_APPLICABLE
  try {
    return window.modagent?.getPLicenseStatusSync?.() || {
      edition: 'subscription',
      state: 'unavailable',
      entitled: false,
    }
  } catch (_) {
    return {
      edition: 'subscription',
      state: 'unavailable',
      entitled: false,
    }
  }
}

export function publishPLicenseStatus(status) {
  window.dispatchEvent(new CustomEvent(P_LICENSE_EVENT, { detail: status }))
}

export function usePLicenseStatus() {
  const [status, setStatus] = useState(readPLicenseStatus)
  useEffect(() => {
    const handle = event => setStatus(event.detail || readPLicenseStatus())
    window.addEventListener(P_LICENSE_EVENT, handle)
    const unsubscribe = window.modagent?.onPLicenseStatus?.(next => {
      publishPLicenseStatus(next)
    })
    window.modagent?.getPLicenseStatus?.()
      .then(next => next && publishPLicenseStatus(next))
      .catch(() => {})
    return () => {
      window.removeEventListener(P_LICENSE_EVENT, handle)
      unsubscribe?.()
    }
  }, [])
  return status
}

export function isPAccessEnabled(status = readPLicenseStatus()) {
  return Boolean(__MODAGENT_SUBSCRIPTION__ && status?.entitled)
}
