// Shared by individual and batch controls. Missing receipts are not success.
export function uninstallOutcome(data, language = 'zh-CN') {
  const en = String(language).startsWith('en')
  const value = data && typeof data === 'object' ? data : {}
  const status = String(value.status || '').toLowerCase()
  const blocked = Boolean(value.error || value.record_retained || value.requires_confirmation
    || value.unsubscribed === false || value.external_config_cleanup?.complete === false
    || value.details?.errors?.length || value.details?.blocked_unsafe?.length
    || value.details?.pending?.length)
  const legacyReceipt = !status && (value.unsubscribed === true
    || (Number.isFinite(value.removed) && value.removed >= 0))
  const complete = !blocked && (status === 'completed' || legacyReceipt)
  return {
    complete,
    message: complete
      ? (en ? 'Uninstall completed.' : '卸载完成。')
      : (en ? 'Uninstall is not fully confirmed. Refresh and review remaining items before retrying.'
        : '卸载未全部确认完成，请刷新并核对剩余项后重新预览。')
        + (value.message || value.error || value.note ? ` ${value.message || value.error || value.note}` : ''),
  }
}
