export function recommendationIdentity(payload) {
  const itemKeys = (payload?.items || [])
    .map(item => String(
      item?.selection_key
      || item?.source_url
      || `${item?.source || ''}:${item?.source_id || ''}:${item?.name || ''}`
    ))
    .filter(Boolean)
    .sort()
  const anchor = Number(payload?.anchor_after_text_count)
  return `${Number.isInteger(anchor) ? anchor : -1}::${itemKeys.join('|')}`
}

export function hasSameRecommendation(messages, payload) {
  const identity = recommendationIdentity(payload)
  return messages.some(message =>
    message.role === 'edition'
    && recommendationIdentity(message.payload) === identity
  )
}
