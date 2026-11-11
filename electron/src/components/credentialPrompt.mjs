// Only structured runtime events can automatically request credentials.
// Model prose, URLs, summaries and raw previews are not trusted instructions.
export function credentialPromptForTool(event, status={}) {
  if(!event || typeof event!=='object')return null
  if(['mod_download','batch_download','nexus_get_detail'].includes(event.name)
      && event.status==='nexus_api_key_missing')return 'nexus'
  if(['nexus_search','mod_recommend','search_mods'].includes(event.name)
      && event.ok===false && status.tavily_set===false)return 'tavily'
  return null
}
