/**
 * Browser-only Nexus conversation cache.
 *
 * The Runtime remains the source of truth for durable history. This cache keeps
 * richer transient UI state (tool cards, local drafts, progress projections),
 * so its key must use the authenticated user id just like the Runtime does.
 */

export const LEGACY_NEXUS_SESSIONS_KEY = 'nexus_demo_sessions_v1'
const SCOPED_NEXUS_SESSIONS_PREFIX = 'nexus_sessions_v2:user:'

function normalizedUserId(userId) {
  const raw = String(userId ?? '').trim()
  if (!/^[1-9]\d{0,18}$/.test(raw)) return ''
  return BigInt(raw).toString()
}

export function nexusSessionsKey(userId) {
  const normalized = normalizedUserId(userId)
  return normalized ? `${SCOPED_NEXUS_SESSIONS_PREFIX}${normalized}` : ''
}

export function createNexusSessionIdentity(userId, username, authToken = '') {
  return Object.freeze({
    userId: normalizedUserId(userId),
    username: String(username || '').trim().toLowerCase(),
    // Memory-only auth epoch. Storage functions never serialize this value.
    authToken: String(authToken || ''),
  })
}

export function isNexusSessionIdentityCurrent(identity, current = {}) {
  const currentUserId = normalizedUserId(current.userId)
  const currentToken = String(current.authToken || '')
  return Boolean(
    identity?.userId
    && identity.userId === currentUserId
    && identity.authToken
    && identity.authToken === currentToken
  )
}

export function isNexusAuthTokenStorageChange(identity, event = {}) {
  if (event.key !== 'token') return false
  return String(event.newValue || '') !== String(identity?.authToken || '')
}

function parseSessions(raw) {
  if (!raw) return null
  try {
    const sessions = JSON.parse(raw)
    if (!Array.isArray(sessions)) return null
    for (const session of sessions) {
      // This recovery marker is page-memory state and must never survive reload.
      if (session && typeof session === 'object' && '_runsRestored' in session) {
        delete session._runsRestored
      }
    }
    return sessions
  } catch {
    return null
  }
}

function cloneSeed(demoSeed) {
  return Array.isArray(demoSeed) ? JSON.parse(JSON.stringify(demoSeed)) : []
}

function mergeSessions(current, legacy) {
  const merged = [...current]
  const knownIds = new Set(current.map((session) => String(session?.id || '')).filter(Boolean))
  for (const session of legacy) {
    const id = String(session?.id || '')
    if (!id || knownIds.has(id)) continue
    merged.push(session)
    knownIds.add(id)
  }
  return merged
}

export function loadNexusSessions({ storage, identity, demoSeed = [] } = {}) {
  if (!storage) return cloneSeed(demoSeed)

  const userId = normalizedUserId(identity?.userId)
  const key = nexusSessionsKey(userId)
  if (!key) return cloneSeed(demoSeed)

  const scoped = parseSessions(storage.getItem(key))
  // identity is frozen from the server-refreshed Pinia auth state at page mount,
  // so late async responses cannot choose a different account's storage key.
  if (userId === '2' && identity?.username === 'teacherdemo') {
    const legacy = parseSessions(storage.getItem(LEGACY_NEXUS_SESSIONS_KEY))
    if (legacy) {
      const migrated = scoped ? mergeSessions(scoped, legacy) : legacy
      // Copy first, then remove. A storage quota failure leaves the legacy source
      // untouched, so the one-time takeover is recoverable on the next load.
      storage.setItem(key, JSON.stringify(migrated))
      try {
        storage.removeItem(LEGACY_NEXUS_SESSIONS_KEY)
      } catch {
        // The scoped copy is already durable. A later teacherDEMO load retries
        // the idempotent merge/cleanup without returning an empty list.
      }
      return migrated
    }
  }

  if (scoped) return scoped
  return cloneSeed(demoSeed)
}

export function saveNexusSessions(sessions, { storage, identity } = {}) {
  if (!storage) return false
  const key = nexusSessionsKey(identity?.userId)
  if (!key) return false
  storage.setItem(key, JSON.stringify(Array.isArray(sessions) ? sessions : []))
  return true
}
