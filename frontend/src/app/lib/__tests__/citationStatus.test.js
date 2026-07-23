import test from 'node:test'
import assert from 'node:assert/strict'

import {
  CITATION_STATUS,
  indexSpansByEvidenceRef,
  mapCitationStatus,
} from '../citationStatus.js'

const citation = {
  key: 'C-1',
  statement: '二分查找要求数组有序',
  evidenceRef: 'ev-42',
  pageOrSlide: 3,
  confidence: 0.9,
}

test('citation 无 key → 证据不足', () => {
  const noKey = { ...citation, key: null }
  assert.deepEqual(mapCitationStatus(noKey, [], {}, {}), CITATION_STATUS.NO_EVIDENCE)
})

test('后端 abstain → 待校验，不推测为通过，附原因', () => {
  const res = mapCitationStatus(citation, [], {}, { abstain: true, abstainReason: 'missing_or_mismatched_sidecar_evidence' })
  assert.equal(res.label, '待校验')
  assert.equal(res.tone, 'neutral')
  assert.equal(res.reason, 'missing_or_mismatched_sidecar_evidence')
})

test('detail.valid===true → 精确引用（用 evidence_ref 关联，非 key）', () => {
  const details = [{ evidence_ref: 'ev-42', valid: true }]
  assert.deepEqual(mapCitationStatus(citation, details, {}, { abstain: false }), CITATION_STATUS.VERIFIED)
})

test('detail.valid===false → 来源失效', () => {
  const details = [{ evidence_ref: 'ev-42', valid: false }]
  assert.deepEqual(mapCitationStatus(citation, details, {}, { abstain: false }), CITATION_STATUS.MISMATCH)
})

test('后端用 evidence_ref 关联，前端假设的 {key,status} 字段不应命中', () => {
  // 旧错误假设的 detail 形态 —— 必须不命中
  const wrongShape = [{ key: 'C-1', status: 'verified' }]
  assert.deepEqual(mapCitationStatus(citation, wrongShape, {}, { abstain: false }), CITATION_STATUS.PENDING)
})

test('无匹配 detail → 待校验', () => {
  const details = [{ evidence_ref: 'other', valid: true }]
  assert.deepEqual(mapCitationStatus(citation, details, {}, { abstain: false }), CITATION_STATUS.PENDING)
})

test('关联 evidence span 状态为 stale → 来源已更新（真实信号优先于 valid）', () => {
  const spans = { 'ev-42': { artifactId: 'ev-42', status: 'stale' } }
  const details = [{ evidence_ref: 'ev-42', valid: true }]
  // 即使 validate 说 valid，span stale 仍优先显示来源已更新
  assert.deepEqual(mapCitationStatus(citation, details, spans, { abstain: false }), CITATION_STATUS.STALE)
})

test('indexSpansByEvidenceRef 用 artifactId 建索引', () => {
  const spans = [
    { artifactId: 'ev-1', status: 'active' },
    { artifactId: 'ev-2', status: 'stale' },
  ]
  const idx = indexSpansByEvidenceRef(spans)
  assert.equal(idx['ev-1'].status, 'active')
  assert.equal(idx['ev-2'].status, 'stale')
  assert.deepEqual(indexSpansByEvidenceRef([]), {})
})
