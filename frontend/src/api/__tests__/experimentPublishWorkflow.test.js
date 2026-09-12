import assert from 'node:assert/strict'
import test from 'node:test'

import {
  distributeWeights,
  isWeightTotalValid,
  pickTargetVersion,
  resolveExperimentSection,
} from '../experimentPublishWorkflow.js'

test('draft without a version resumes at test authoring', () => {
  assert.equal(resolveExperimentSection({ publish_status: 'draft', default_version_id: null }), 'tests')
})

test('draft with an active version resumes at the publish checklist', () => {
  assert.equal(resolveExperimentSection({ publish_status: 'draft', default_version_id: 'expv-1' }), 'publish')
})

test('published definition resumes at the publish checklist for read-only review', () => {
  assert.equal(resolveExperimentSection({ publish_status: 'published', default_version_id: 'expv-1' }), 'publish')
})

test('no definition falls back to the basics section', () => {
  assert.equal(resolveExperimentSection(null), 'basics')
})

test('publish target prefers the newest unlocked version', () => {
  const target = pickTargetVersion([
    { version_id: 'v1', version_number: 1, is_locked: true, is_active: true },
    { version_id: 'v2', version_number: 2, is_locked: false, is_active: false },
  ])
  assert.equal(target.version_id, 'v2')
})

test('publish target falls back to the active version when everything is locked', () => {
  const target = pickTargetVersion([
    { version_id: 'v1', version_number: 1, is_locked: true, is_active: true },
    { version_id: 'v2', version_number: 2, is_locked: true, is_active: false },
  ])
  assert.equal(target.version_id, 'v1')
})

test('publish target is null for an experiment without versions', () => {
  assert.equal(pickTargetVersion([]), null)
  assert.equal(pickTargetVersion(undefined), null)
})

test('auto distributed weights always total exactly one', () => {
  for (const count of [1, 2, 3, 4, 6, 7, 8, 10, 15, 30]) {
    const weights = distributeWeights(count)
    assert.equal(weights.length, count)
    assert.ok(
      isWeightTotalValid(weights.map((weight) => ({ weight }))),
      `count=${count} sum=${weights.reduce((a, b) => a + b, 0)}`,
    )
    // 分配尽量均匀：极差不超过 1 分。
    assert.ok(Math.max(...weights) - Math.min(...weights) <= 0.0101, `count=${count}`)
  }
})

test('weight validation mirrors the server tolerance', () => {
  assert.equal(isWeightTotalValid([{ weight: 0.34 }, { weight: 0.33 }, { weight: 0.33 }]), true)
  assert.equal(isWeightTotalValid([{ weight: 0.5 }, { weight: 0.5 }, { weight: 0 }]), true)
  assert.equal(isWeightTotalValid([{ weight: 0.5 }, { weight: 0.4 }]), false)
  assert.equal(isWeightTotalValid([]), false)
})
