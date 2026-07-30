import request from '@/utils/request.js'
import { fetchProtectedImageUrl } from '@/api/evidence.js'

/**
 * P2 批次3 知识图谱 API
 *
 * 全部对接真实 V1 端点，响应经 request.js 统一剥离 code/message。
 * 端点前缀：/api/v1/graph
 *
 * 权限模型（与后端 course-access 一致）：
 * - 学生：只能读取已发布快照、查询节点先修/后继；
 * - 教师：可发起评审流转、发布/回滚快照、增删证据；
 * - 所有调用必须携带 courseId，确保课程级隔离。
 */

// ---------------------------------------------------------------------------
// 学生端：只读已发布快照
// ---------------------------------------------------------------------------

/**
 * 获取课程当前已发布的知识图谱快照。
 * GET /graph/course/{courseId}/snapshot
 *
 * 学生视角：后端只返回 published 状态的快照；
 * 无已发布快照时返回 null（由调用方展示空状态，不伪造数据）。
 *
 * @param {number|string} courseId - 课程 ID
 * @returns {Promise<Object|null>} 快照对象（含 nodes/edges/policy_version 等），或 null
 */
export function getCourseSnapshot(courseId) {
  return request.get(`/graph/course/${courseId}/snapshot`)
}

/**
 * 获取某个知识点的一跳先修/后继节点。
 * GET /graph/course/{courseId}/nodes/{nodeId}/prerequisites?direction=incoming|outgoing
 *
 * @param {number|string} courseId - 课程 ID
 * @param {number|string} nodeId - 知识点节点 ID
 * @param {'incoming'|'outgoing'} [direction='incoming'] - incoming=先修，outgoing=后继
 * @returns {Promise<Object>} 包含 items 数组（来自后端 prerequisites 端点）
 */
export function getNodePrerequisites(courseId, nodeId, direction = 'incoming') {
  return request.get(
    `/graph/course/${courseId}/nodes/${nodeId}/prerequisites`,
    { params: { direction } },
  )
}

// ---------------------------------------------------------------------------
// 教师端：图谱治理与证据
// ---------------------------------------------------------------------------

/**
 * 列出待评审的候选变更。
 * GET /graph/course/{courseId}/candidates
 *
 * @param {number|string} courseId - 课程 ID
 * @param {Object} [params] - 查询参数（status/page_size 等）
 * @returns {Promise<Object>} 包含 items 列表
 */
export function listCandidates(courseId, params = {}) {
  return request.get(`/graph/course/${courseId}/candidates`, { params })
}

/**
 * 教师评审流转：通过/驳回/挂起候选变更。
 * POST /graph/course/{courseId}/reviews/{reviewId}/transition
 *
 * 后端 ReviewTransitionRequest 接受 new_decision、review_comment、evidence_ids。
 *
 * @param {number|string} courseId - 课程 ID
 * @param {number|string} reviewId - 评审单 ID（数据库行 id）
 * @param {Object} payload - { new_decision, review_comment?, evidence_ids? }
 * @returns {Promise<Object>} 评审后的最新状态
 */
export function transitionReview(courseId, reviewId, payload) {
  return request.post(
    `/graph/course/${courseId}/reviews/${reviewId}/transition`,
    payload,
  )
}

/**
 * 列出课程的所有快照（含未发布）。
 * GET /graph/course/{courseId}/snapshots
 *
 * @param {number|string} courseId
 * @returns {Promise<Object>} { items: [...] }
 */
export function listSnapshots(courseId) {
  return request.get(`/graph/course/${courseId}/snapshots`)
}

/**
 * 对比两个快照的差异。
 * GET /graph/course/{courseId}/snapshots/diff?a={snapshotAId}&b={snapshotBId}
 *
 * @param {number|string} courseId
 * @param {string} snapshotAId - 起始快照
 * @param {string} snapshotBId - 目标快照
 * @returns {Promise<Object>} { added, removed, changed, ... }
 */
export function diffSnapshots(courseId, snapshotAId, snapshotBId) {
  return request.get(`/graph/course/${courseId}/snapshots/diff`, {
    params: { a: snapshotAId, b: snapshotBId },
  })
}

/**
 * 发布快照（学生可见）。
 * POST /graph/course/{courseId}/publish
 *
 * 后端 PublishSnapshotRequest 接受 nodes、relations、label；
 * 调用此接口会创建新的不可变 GraphSnapshot 并将旧快照置为 SUPERSEDED。
 *
 * @param {number|string} courseId
 * @param {Object} payload - { nodes, relations, label? }
 * @returns {Promise<Object>} 发布后的快照元信息
 */
export function publishSnapshot(courseId, payload) {
  return request.post(`/graph/course/${courseId}/publish`, payload)
}

/** Publish the current fully reviewed candidate batch. The server assembles
 * stable node identities, active Evidence and student-readable citation refs.
 */
export function publishReviewedSnapshot(courseId, payload = {}) {
  return request.post(`/graph/course/${courseId}/publish-reviewed`, payload)
}

/**
 * 回滚到指定快照。
 * POST /graph/course/{courseId}/rollback/{snapshotId}
 *
 * @param {number|string} courseId
 * @param {string} snapshotId - 目标快照 ID (UUID)
 * @returns {Promise<Object>} 回滚结果
 */
export function rollbackSnapshot(courseId, snapshotId) {
  return request.post(
    `/graph/course/${courseId}/rollback/${snapshotId}`,
  )
}

/**
 * 列出课程关联的学习证据（教师/治理视角）。
 * GET /graph/course/{courseId}/evidence
 *
 * @param {number|string} courseId
 * @param {Object} [params] - 查询参数（status/page_size 等）
 * @returns {Promise<Object>} { items: [...] }
 */
export function listEvidence(courseId, params = {}) {
  return request.get(`/graph/course/${courseId}/evidence`, { params })
}

/** List candidate/confirmed evidence spans for teacher evidence governance. */
export function listEvidenceSpans(courseId, params = {}) {
  return request.get(`/graph/course/${courseId}/evidence-spans`, { params })
}

/** Confirm one candidate span and promote it to formal Evidence + Citation. */
export function confirmEvidenceSpan(courseId, spanId, payload = {}) {
  return request.post(
    `/graph/course/${courseId}/evidence-spans/${encodeURIComponent(spanId)}/confirm`,
    payload,
  )
}

/** Reject one candidate span with an auditable reason. */
export function rejectEvidenceSpan(courseId, spanId, payload = {}) {
  return request.post(
    `/graph/course/${courseId}/evidence-spans/${encodeURIComponent(spanId)}/reject`,
    payload,
  )
}

/** List formal student-readable citations (teacher view may include stale). */
export function listCourseCitations(courseId, params = {}) {
  return request.get(`/graph/course/${courseId}/citations`, { params })
}

export { fetchProtectedImageUrl }

// ---------------------------------------------------------------------------
// Immutable CourseKnowledgeBundle
// ---------------------------------------------------------------------------

export function getKnowledgeBundleDraft(courseId) {
  return request.get(`/graph/course/${courseId}/knowledge-bundle/draft`)
}

export function regenerateKnowledgeBundle(courseId, payload) {
  return request.post(`/graph/course/${courseId}/knowledge-bundle/regenerate`, payload)
}

export function approveKnowledgeBundle(courseId, payload) {
  return request.post(`/graph/course/${courseId}/knowledge-bundle/approve`, payload)
}

export function bootstrapKnowledgeBundle(courseId) {
  return request.post(`/graph/course/${courseId}/knowledge-bundle/bootstrap`, {
    confirm_existing_snapshot: true,
  })
}

export function getKnowledgeBundleStatus(courseId) {
  return request.get(`/graph/course/${courseId}/knowledge-bundle/status`)
}

export function listKnowledgeBundles(courseId) {
  return request.get(`/graph/course/${courseId}/knowledge-bundles`)
}

export function diffKnowledgeBundles(courseId, fromBundleId, toBundleId) {
  return request.get(`/graph/course/${courseId}/knowledge-bundles/diff`, {
    params: { from_bundle_id: fromBundleId, to_bundle_id: toBundleId },
  })
}

export function rollbackKnowledgeBundle(courseId, bundleId) {
  return request.post(`/graph/course/${courseId}/knowledge-bundles/${bundleId}/rollback`)
}

export function getActiveKnowledgeBundle(courseId) {
  return request.get(`/graph/course/${courseId}/knowledge-bundle/active`)
}

export function getActiveKnowledgeGraph(courseId) {
  return request.get(`/graph/course/${courseId}/knowledge-bundle/graph`)
}

export function getActiveKnowledgeNode(courseId, nodeKey) {
  return request.get(
    `/graph/course/${courseId}/knowledge-bundle/nodes/${encodeURIComponent(nodeKey)}`,
  )
}

export function searchActiveKnowledge(courseId, query, topK = 6) {
  return request.get(`/graph/course/${courseId}/knowledge-bundle/search`, {
    params: { q: query, top_k: topK },
  })
}

/**
 * 添加学习证据（关联课程与文档）。
 * POST /graph/course/{courseId}/evidence
 *
 * @param {number|string} courseId
 * @param {Object} payload - { document_id, evidence_type, ... }
 * @returns {Promise<Object>} 创建后的证据对象
 */
export function addEvidence(courseId, payload) {
  return request.post(`/graph/course/${courseId}/evidence`, payload)
}

/**
 * 标记某条证据为已失效（来源文档已变更）。
 * POST /graph/course/{courseId}/mark-stale?document_id=...
 *
 * 后端使用 Query 参数 document_id 接收课件文档 UUID；
 * 课件重新解析或删除时历史引用不会静默指向错误内容。
 *
 * @param {number|string} courseId
 * @param {string} documentId - 关联文档 UUID
 * @returns {Promise<Object>} 操作结果 { stale_count, document_id }
 */
export function markEvidenceStale(courseId, documentId) {
  return request.post(
    `/graph/course/${courseId}/mark-stale`,
    {},
    { params: { document_id: documentId } },
  )
}
