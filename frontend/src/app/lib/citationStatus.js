/**
 * 引用状态映射（纯函数，可单测）。
 *
 * 后端 validate_citations 真实返回（evidence_v2.py:210）：
 *   details: [{ evidence_ref, valid: bool }]  ← 不是 {key, status}
 *   status: 'valid' | 'abstain'
 *   abstain: bool, abstainReason: string|null
 *
 * page-design §6.8 要求区分：精确引用 / 近似匹配 / 来源已更新 / 来源失效 / 证据不足。
 * 后端只给二元 valid + abstain，不给 partial/mismatch 细分；但 evidence span 的
 * status(STALE) 是真实信号，可交叉引用推出「来源已更新」。其余严格按真实信号映射，
 * 不推测为通过。
 */

export const CITATION_STATUS = Object.freeze({
  VERIFIED: { label: '精确引用', tone: 'green' },
  PARTIAL: { label: '近似匹配', tone: 'amber' },
  STALE: { label: '来源已更新', tone: 'amber' },
  MISMATCH: { label: '来源失效', tone: 'red' },
  NO_EVIDENCE: { label: '证据不足', tone: 'red' },
  PENDING: { label: '待校验', tone: 'neutral' },
})

/**
 * @param {Object} citation - parseCitation 结果 {key, statement, evidenceRef, ...}
 * @param {Array} validateDetails - [{evidence_ref, valid}]
 * @param {Object} spansByEvidenceRef - {evidenceRef: span}（span.status 可为 stale）
 * @param {Object} validateMeta - {abstain, abstainReason}
 * @returns {{label, tone, reason?}}
 */
export function mapCitationStatus(citation, validateDetails = [], spansByEvidenceRef = {}, validateMeta = {}) {
  // 无 key → 前端无证据锚点可校验
  if (!citation || citation.key == null) {
    return CITATION_STATUS.NO_EVIDENCE
  }

  // Course-scoped citation responses carry an auditable source status even
  // though they do not expose the admin-only V2 validation endpoint.  Prefer
  // that signal over guessing "verified" from the presence of a citation.
  const sourceStatus = String(citation.metadata?.sourceStatus ?? '').toLowerCase()
  if (sourceStatus === 'exact' || sourceStatus === 'verified') return CITATION_STATUS.VERIFIED
  if (sourceStatus === 'approximate' || sourceStatus === 'partial') return CITATION_STATUS.PARTIAL
  if (sourceStatus === 'stale' || sourceStatus === 'source_updated') return CITATION_STATUS.STALE
  if (sourceStatus === 'source_invalid' || sourceStatus === 'orphaned' || sourceStatus === 'mismatch') {
    return CITATION_STATUS.MISMATCH
  }

  // 关联的证据 span 已 stale → 来源已更新（真实信号）
  const linkedSpan = citation.evidenceRef ? spansByEvidenceRef[citation.evidenceRef] : null
  if (linkedSpan && linkedSpan.status === 'stale') {
    return CITATION_STATUS.STALE
  }

  // 后端 abstain（sidecar 缺失等）→ 无法校验，显式待校验，不推测为通过
  if (validateMeta.abstain) {
    return { ...CITATION_STATUS.PENDING, reason: validateMeta.abstainReason || '后端无法校验' }
  }

  // 找到对应 detail（后端用 evidence_ref 关联，非 key）
  const detail = validateDetails.find(
    (d) => d && (d.evidence_ref === citation.evidenceRef || d.evidenceRef === citation.evidenceRef)
  )

  if (!detail) {
    return CITATION_STATUS.PENDING
  }

  // 后端只给二元 valid：true→精确引用，false→来源失效（mismatch）
  return detail.valid === true ? CITATION_STATUS.VERIFIED : CITATION_STATUS.MISMATCH
}

/** 构建 evidenceRef → span 索引，供 mapCitationStatus 交叉引用 stale 状态 */
export function indexSpansByEvidenceRef(spans = []) {
  const map = {}
  for (const span of spans) {
    // evidence span 的 artifactId/unitId/blockId 组合可作为 evidenceRef；
    // parseEvidenceSpan 未直接暴露 evidenceRef，用 artifactId 作键（与后端 evidence_ref 对应）
    const ref = span?.artifactId || span?.evidenceRef
    if (ref) map[ref] = span
  }
  return map
}
