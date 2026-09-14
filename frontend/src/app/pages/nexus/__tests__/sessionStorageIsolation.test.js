import test from 'node:test'
import assert from 'node:assert/strict'

import {
  LEGACY_NEXUS_SESSIONS_KEY,
  createNexusSessionIdentity,
  isNexusAuthTokenStorageChange,
  isNexusSessionIdentityCurrent,
  nexusSessionsKey,
  loadNexusSessions,
  saveNexusSessions,
} from '../sessionStorageIsolation.js'

class MemoryStorage {
  constructor(entries = {}) {
    this.values = new Map(Object.entries(entries))
  }

  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null
  }

  setItem(key, value) {
    this.values.set(key, String(value))
  }

  removeItem(key) {
    this.values.delete(key)
  }
}

test('uses the authenticated user id as the Nexus session cache namespace', () => {
  assert.notEqual(nexusSessionsKey('2'), nexusSessionsKey('68'))
  assert.equal(nexusSessionsKey(' 2 '), nexusSessionsKey('2'))
  assert.equal(nexusSessionsKey('2!'), '')
})

test('a non-teacherDEMO account cannot read the legacy shared cache', () => {
  const legacy = [{ id: 'legacy-session', turns: [{ question: 'private' }] }]
  const storage = new MemoryStorage({
    userId: '68',
    username: 'studentDEMO',
    [LEGACY_NEXUS_SESSIONS_KEY]: JSON.stringify(legacy),
  })

  const identity = createNexusSessionIdentity('68', 'studentDEMO')
  assert.deepEqual(loadNexusSessions({ storage, identity, demoSeed: [] }), [])
  assert.equal(storage.getItem(LEGACY_NEXUS_SESSIONS_KEY), JSON.stringify(legacy))
})

test('spoofing the local username cannot claim the legacy cache from another user id', () => {
  const legacy = [{ id: 'legacy-session' }]
  const storage = new MemoryStorage({
    userId: '68',
    username: 'teacherDEMO',
    [LEGACY_NEXUS_SESSIONS_KEY]: JSON.stringify(legacy),
  })

  const identity = createNexusSessionIdentity('68', 'teacherDEMO')
  assert.deepEqual(loadNexusSessions({ storage, identity, demoSeed: [] }), [])
  assert.equal(storage.getItem(LEGACY_NEXUS_SESSIONS_KEY), JSON.stringify(legacy))
  assert.equal(storage.getItem(nexusSessionsKey('68')), null)
})

test('teacherDEMO exclusively takes over and removes the legacy shared cache', () => {
  const legacy = [{ id: 'legacy-session', turns: [{ question: 'owned by teacher demo' }] }]
  const storage = new MemoryStorage({
    userId: '2',
    username: 'TeacherDemo',
    [LEGACY_NEXUS_SESSIONS_KEY]: JSON.stringify(legacy),
  })

  const identity = createNexusSessionIdentity('2', 'TeacherDemo')
  assert.deepEqual(loadNexusSessions({ storage, identity, demoSeed: [] }), legacy)
  assert.equal(storage.getItem(LEGACY_NEXUS_SESSIONS_KEY), null)
  assert.deepEqual(JSON.parse(storage.getItem(nexusSessionsKey('2'))), legacy)
})

test('saving and loading remain isolated between authenticated users', () => {
  const storage = new MemoryStorage({ userId: '2', username: 'teacherDEMO' })
  const teacherIdentity = createNexusSessionIdentity('2', 'teacherDEMO')
  saveNexusSessions([{ id: 'teacher-only' }], { storage, identity: teacherIdentity })

  storage.setItem('userId', '68')
  storage.setItem('username', 'studentDEMO')
  const studentIdentity = createNexusSessionIdentity('68', 'studentDEMO')
  assert.deepEqual(loadNexusSessions({ storage, identity: studentIdentity, demoSeed: [] }), [])
  saveNexusSessions([{ id: 'student-only' }], { storage, identity: studentIdentity })

  storage.setItem('userId', '2')
  storage.setItem('username', 'teacherDEMO')
  assert.deepEqual(loadNexusSessions({ storage, identity: teacherIdentity, demoSeed: [] }), [{ id: 'teacher-only' }])
})

test('real mode can opt out of demo seeds for a new authenticated user', () => {
  const storage = new MemoryStorage({ userId: '295', username: 'demo-user' })
  const identity = createNexusSessionIdentity('295', 'demo-user')
  assert.deepEqual(loadNexusSessions({ storage, identity, demoSeed: [] }), [])
})

test('a page keeps saving to its mount-time identity after the global account changes', () => {
  const storage = new MemoryStorage({ userId: '2', username: 'teacherDEMO' })
  const mountedIdentity = createNexusSessionIdentity('2', 'teacherDEMO')

  storage.setItem('userId', '68')
  storage.setItem('username', 'studentDEMO')
  saveNexusSessions([{ id: 'late-teacher-response' }], { storage, identity: mountedIdentity })

  assert.deepEqual(JSON.parse(storage.getItem(nexusSessionsKey('2'))), [{ id: 'late-teacher-response' }])
  assert.equal(storage.getItem(nexusSessionsKey('68')), null)
})

test('a token change invalidates the mounted Nexus identity even when user id is stale', () => {
  const identity = createNexusSessionIdentity('2', 'teacherDEMO', 'token-a')

  assert.equal(isNexusSessionIdentityCurrent(identity, { userId: '2', authToken: 'token-a' }), true)
  assert.equal(isNexusSessionIdentityCurrent(identity, { userId: '2', authToken: 'token-b' }), false)
})

test('only a different token storage event invalidates the mounted Nexus page', () => {
  const identity = createNexusSessionIdentity('2', 'teacherDEMO', 'token-a')

  assert.equal(isNexusAuthTokenStorageChange(identity, { key: 'token', newValue: 'token-b' }), true)
  assert.equal(isNexusAuthTokenStorageChange(identity, { key: 'token', newValue: 'token-a' }), false)
  assert.equal(isNexusAuthTokenStorageChange(identity, { key: 'username', newValue: 'studentDEMO' }), false)
})

test('a successful legacy copy survives cleanup failure without being overwritten', () => {
  const legacy = [{ id: 'legacy-session' }]
  const storage = new MemoryStorage({
    userId: '2',
    username: 'teacherDEMO',
    [LEGACY_NEXUS_SESSIONS_KEY]: JSON.stringify(legacy),
  })
  storage.removeItem = () => { throw new Error('storage cleanup blocked') }
  const identity = createNexusSessionIdentity('2', 'teacherDEMO')

  assert.deepEqual(loadNexusSessions({ storage, identity, demoSeed: [] }), legacy)
  assert.deepEqual(JSON.parse(storage.getItem(nexusSessionsKey('2'))), legacy)
})

test('teacherDEMO merges a leftover legacy cache into an existing scoped cache', () => {
  const storage = new MemoryStorage({
    [nexusSessionsKey('2')]: JSON.stringify([{ id: 'current' }, { id: 'same', title: 'current title' }]),
    [LEGACY_NEXUS_SESSIONS_KEY]: JSON.stringify([{ id: 'legacy' }, { id: 'same', title: 'old title' }]),
  })
  const identity = createNexusSessionIdentity('2', 'teacherDEMO')

  assert.deepEqual(loadNexusSessions({ storage, identity, demoSeed: [] }), [
    { id: 'current' },
    { id: 'same', title: 'current title' },
    { id: 'legacy' },
  ])
  assert.equal(storage.getItem(LEGACY_NEXUS_SESSIONS_KEY), null)
})
