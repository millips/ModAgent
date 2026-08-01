import { useEffect, useState } from 'react'

const PROFILE_KEY = 'modagent-p-share-profile-v1'
const SUBMISSIONS_KEY = 'modagent-p-share-submissions-v1'
export const P_SHARE_CHANGE_EVENT = 'modagent:p-share-changed'

function readJson(key, fallback) {
  try {
    const value = JSON.parse(window.localStorage.getItem(key) || '')
    return value && typeof value === 'object' ? value : fallback
  } catch (_) {
    return fallback
  }
}

function notify() {
  window.dispatchEvent(new CustomEvent(P_SHARE_CHANGE_EVENT))
}

export function readPShareProfile() {
  return readJson(PROFILE_KEY, null)
}

export function isPShareActive() {
  return Boolean(readPShareProfile()?.enrolled_at)
}

export function activatePShare(displayName = '') {
  const profile = {
    version: 1,
    enrolled_at: new Date().toISOString(),
    display_name: String(displayName || '').trim().slice(0, 80),
  }
  window.localStorage.setItem(PROFILE_KEY, JSON.stringify(profile))
  notify()
  return profile
}

export function readPShareSubmissions() {
  const value = readJson(SUBMISSIONS_KEY, [])
  return Array.isArray(value) ? value : []
}

export function upsertPShareSubmission(submission) {
  if (!submission?.submission_id) return null
  const entries = readPShareSubmissions()
  const now = new Date().toISOString()
  const normalized = {
    version: 1,
    status: 'draft',
    created_at: now,
    updated_at: now,
    title: '未命名合集',
    game_name: '',
    game_slug: '',
    mod_count: 0,
    warning: '',
    description: '',
    issue_url: '',
    ma_code: '',
    ...submission,
    updated_at: now,
  }
  const index = entries.findIndex(item => item.submission_id === normalized.submission_id)
  if (index >= 0) entries[index] = { ...entries[index], ...normalized }
  else entries.unshift(normalized)
  window.localStorage.setItem(SUBMISSIONS_KEY, JSON.stringify(entries))
  notify()
  return normalized
}

export function updatePShareSubmission(submissionId, patch) {
  const entries = readPShareSubmissions()
  const index = entries.findIndex(item => item.submission_id === submissionId)
  if (index < 0) return null
  const next = {
    ...entries[index],
    ...patch,
    updated_at: new Date().toISOString(),
  }
  entries[index] = next
  window.localStorage.setItem(SUBMISSIONS_KEY, JSON.stringify(entries))
  notify()
  return next
}

export function usePShareProfile() {
  const [profile, setProfile] = useState(readPShareProfile)
  useEffect(() => {
    const refresh = () => setProfile(readPShareProfile())
    window.addEventListener(P_SHARE_CHANGE_EVENT, refresh)
    return () => window.removeEventListener(P_SHARE_CHANGE_EVENT, refresh)
  }, [])
  return profile
}

export function usePShareSubmissions() {
  const [submissions, setSubmissions] = useState(readPShareSubmissions)
  useEffect(() => {
    const refresh = () => setSubmissions(readPShareSubmissions())
    window.addEventListener(P_SHARE_CHANGE_EVENT, refresh)
    return () => window.removeEventListener(P_SHARE_CHANGE_EVENT, refresh)
  }, [])
  return submissions
}
