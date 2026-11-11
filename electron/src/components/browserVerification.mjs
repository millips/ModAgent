export function browserVerificationSite(event) {
  if(!event || typeof event!=='object')return null
  if(!['manual_action_required','partial_manual_action_required','login_required','waiting_verification'].includes(event.status))return null
  if(['mod_download','batch_download','nexus_get_detail'].includes(event.name))return 'nexus'
  if(['workshop_install','workshop_search'].includes(event.name))return 'steam'
  return null
}

export function revealBrowserForVerification(event,key) {
  const site=browserVerificationSite(event)
  if(site && typeof window.modagent?.showBrowser==='function') {
    // Only structured tool statuses request attention. Never interpret model text/URLs.
    Promise.resolve(window.modagent.showBrowser({site,automatic:true,key})).catch(()=>{})
  }
}
