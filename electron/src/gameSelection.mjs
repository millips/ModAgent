import {requestLocalJson, LocalApiError} from './components/localApi.mjs'
import {validateRuntimeStatus} from './runtimeStatus.mjs'

const normalizedPath = value => String(value || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
// Read-only recovery is offered only after a validated save acknowledgement.
export async function verifyGameSelection(api, game, {request = requestLocalJson} = {}) {
  if (!game?.slug || !game?.path) throw new LocalApiError('GAME_SELECTION_INVALID')
  const status = validateRuntimeStatus(await request(api + '/status'))
  if (status.game_slug !== game.slug || normalizedPath(status.game_root) !== normalizedPath(game.path)
      || (game.game_instance_id && status.game_instance_id !== game.game_instance_id)) {
    throw new LocalApiError('GAME_SELECTION_MISMATCH')
  }
  return status
}
async function verifySavedGame(api, game, request) {
  try { return await verifyGameSelection(api, game, {request}) }
  catch (error) { error.confirmedGame = {...game}; throw error }
}
export async function importGameSelection(api, payload, {request = requestLocalJson} = {}) {
  const result = await request(api + '/games/import', {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload),
  }, {timeoutMs:120000})
  const game = result?.game
  if (result?.saved !== true || typeof game?.name !== 'string' || !game.name
      || typeof game.path !== 'string' || !game.path || typeof game.slug !== 'string' || !game.slug
      || typeof game.game_instance_id !== 'string' || !game.game_instance_id) throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
  const status = await verifySavedGame(api, game, request)
  return {result,status}
}
export async function saveGameSelection(api, game, {request = requestLocalJson} = {}) {
  if (!game || typeof game.name !== 'string' || !game.name.trim() || typeof game.path !== 'string' || !game.path.trim()) {
    throw new LocalApiError('GAME_SELECTION_INVALID')
  }
  let slug = game.slug || ('local_' + game.name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0,40))
  let gameId = game.game_id
  if (!game.slug) {
    try {
      const resolved = await request(api + '/games/resolve?name=' + encodeURIComponent(game.name))
      if (typeof resolved?.slug === 'string' && resolved.slug) { slug = resolved.slug; gameId = resolved.game_id }
    } catch { /* Unknown games retain the existing local/open-mode fallback. */ }
  }
  const result = await request(api + '/config', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({game_name:game.name, game_slug:slug, game_instance_id:game.game_instance_id || '', game_id:gameId, game_root:game.path}),
  })
  if (result?.ok !== true) throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
  return verifySavedGame(api, {...game, slug}, request)
}
