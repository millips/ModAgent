export function inventoryFeedback(state, language='zh-CN') {
  const en=language==='en'
  if(state.status==='completed'){
    const missing=state.missing_roots?.length||0
    if(missing)return {kind:'warn',message:'[SCAN_PARTIAL] '+(en
      ? `Background scan incomplete: ${missing} saved mod directories could not be found. ${state.imported} new records were imported from available directories. Reconnect the drive or update the saved directories, then scan again. This does not mean those Mods are uninstalled.`
      : `后台扫描不完整：${missing} 个已保存的模组目录未找到，已从可用目录新增导入 ${state.imported} 条记录。请连接磁盘或更新已保存的目录后重新扫描；不能据此判断其中的 Mod 已卸载。`)}
    return {kind:'success',message:en
      ? `Scan completed: ${state.detected} detected, ${state.imported} added to inventory.`
      : `扫描完成：发现 ${state.detected} 项，清单新增 ${state.imported} 项。`}
  }
  if(state.status==='failed'&&state.error_code==='SCAN_DIRECTORY_UNREADABLE')return {
    kind:'warn',message:'[SCAN_DIRECTORY_UNREADABLE] '+(en
      ? 'The mod directory could not be read completely. Check folder permissions and drive connectivity, then scan again. The saved game/directory has not been removed.'
      : '无法完整读取模组目录。请检查文件夹权限和磁盘连接后重新扫描；已保存的游戏或目录未被移除。')}
  return {kind:'warn',message:en
    ? (state.status==='failed'?'[SCAN_FAILED] Background scan failed. Check diagnostics and the Mod list; the saved game/directory has not been removed.':'[SCAN_STATUS_UNCONFIRMED] Scan status could not be confirmed. It may still be running. Check the Mod list before starting another scan.')
    : (state.status==='failed'?'[SCAN_FAILED] 后台扫描失败，请检查诊断和 Mod 清单；已保存的游戏或目录未被移除。':'[SCAN_STATUS_UNCONFIRMED] 扫描状态未能确认，后台可能仍在运行。请先检查 Mod 清单再发起新扫描。')}
}
