/**
 * P1-04 Evidence API module.
 *
 * Provides functions to fetch document page images, citations, and evidence
 * data from the backend. This module calls the REAL V2 endpoint
 * ``/api/v1/evidence-v2`` (frozen contract ``internal-evidence-api/1.0``);
 * it does NOT fall back to fixture data — a failed fetch throws. It is
 * consumed by the production Evidence Viewer (admin-only route) and the
 * graph-browser evidence layer.
 *
 * RISK-02: All API responses are validated through the contracts module
 * before being passed to viewer components. Invalid or stale data is
 * explicitly flagged rather than silently displayed.
 */

import {
  parseCitation,
  parseEvidenceSpan,
  parseCitationValidationResult,
  EvidenceStatus,
} from '../features/evidence-viewer/contracts.js'
import request from '../utils/request.js'

/**
 * @typedef {Object} DocumentPageResponse
 * @property {string} documentId
 * @property {number} pageNumber - 1-based
 * @property {string} imageUrl - URL to the rendered page image
 * @property {number} naturalWidth - Image natural width in pixels
 * @property {number} naturalHeight - Image natural height in pixels
 */

/**
 * @typedef {Object} CitationResponse
 * @property {string} key
 * @property {string} statement
 * @property {Array} evidenceSpans
 */

/**
 * @typedef {Object} EvidenceValidationResponse
 * @property {string} status
 * @property {boolean} abstain
 * @property {Array} details
 */

// ---------------------------------------------------------------------------
// API base URL configuration
// ---------------------------------------------------------------------------

/** Base URL for evidence API endpoints (frozen internal-evidence-api/1.0). */
let API_BASE = '/api/v1/evidence-v2'

/**
 * Set the API base URL (called by P1-09 during integration).
 * @param {string} baseUrl
 */
export function setEvidenceApiBase(baseUrl) {
  API_BASE = baseUrl
}

/**
 * 构建带鉴权的请求头。evidence-v2 端点 admin-only（ADR-0006 §9），
 * 裸 fetch 不带 token 会被鉴权依赖拒绝（401/403）。统一注入 Bearer token，
 * 与 request.js 行为一致；无 token 时返回空 headers（端点仍可能公开可读时可用）。
 */
function authHeaders() {
  const token = typeof localStorage !== 'undefined' ? localStorage.getItem('token') : null
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/**
 * 统一 fetch 包装：注入鉴权头，失败抛带状态码的 Error（便于上层按 403/503 分类）。
 */
async function evidenceFetch(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { ...authHeaders(), ...options.headers },
  })
  if (!response.ok) {
    throw new Error(`evidence request failed: ${response.status}`)
  }
  return response
}

// ---------------------------------------------------------------------------
// Document page images
// ---------------------------------------------------------------------------

/**
 * Fetch a rendered page image for a document.
 *
 * @param {string} documentId - Stable document ID
 * @param {number} pageNumber - 1-based page number
 * @returns {Promise<DocumentPageResponse>}
 */
export async function fetchPageImage(documentId, pageNumber) {
  const url = `${API_BASE}/documents/${encodeURIComponent(documentId)}/pages/${pageNumber}/image`
  const response = await evidenceFetch(url)
  const data = await response.json()
  return {
    documentId: data.document_id ?? data.documentId ?? documentId,
    pageNumber: data.page_number ?? data.pageNumber ?? pageNumber,
    imageUrl: data.image_url ?? data.imageUrl ?? '',
    naturalWidth: data.natural_width ?? data.naturalWidth ?? 0,
    naturalHeight: data.natural_height ?? data.naturalHeight ?? 0,
  }
}

/**
 * Fetch all page image URLs for a document.
 *
 * @param {string} documentId
 * @returns {Promise<Array<string>>} Ordered array of image URLs, index 0 = page 1
 */
export async function fetchDocumentPages(documentId) {
  const url = `${API_BASE}/documents/${encodeURIComponent(documentId)}/pages`
  const response = await evidenceFetch(url)
  const data = await response.json()
  return Array.isArray(data) ? data : (data.pages ?? [])
}

/** Fetch a protected course page and return a browser-safe blob URL. */
export async function fetchProtectedImageUrl(url) {
  if (!url) return null
  const relativeUrl = url.replace(/^\/api\/v1\//, '')
  const blob = await request.get(relativeUrl, { responseType: 'blob' })
  if (!(blob instanceof Blob)) throw new Error('Evidence render did not return an image')
  return URL.createObjectURL(blob)
}

// ---------------------------------------------------------------------------
// Citations
// ---------------------------------------------------------------------------

/**
 * Fetch citations for a specific document.
 *
 * @param {string} documentId
 * @param {Object} [options]
 * @param {number} [options.page] - Filter to a specific page
 * @returns {Promise<Array>} Array of parsed Citation objects
 */
export async function fetchCitations(documentId, options = {}) {
  let url = `${API_BASE}/documents/${encodeURIComponent(documentId)}/citations`
  if (options.page != null) {
    url += `?page=${options.page}`
  }
  const response = await evidenceFetch(url)
  const data = await response.json()
  const items = Array.isArray(data) ? data : (data.citations ?? [])
  return items.map(item => parseCitation(item)).filter(Boolean)
}

/**
 * Fetch learner-facing citations through the course-scoped production API.
 *
 * The internal ``evidence-v2`` routes above are deliberately admin-only and
 * must not be used by the learning workspace.  This adapter keeps the
 * evidence-viewer shape while preserving the course citation status and the
 * signed page-render URL returned by the graph/document-parse API.
 */
export async function fetchCourseCitations(courseId, options = {}) {
  if (courseId == null || courseId === '') return []
  const data = await request.get(
    `graph/course/${encodeURIComponent(courseId)}/citations`,
    { params: options },
  )
  const items = Array.isArray(data) ? data : (data?.items ?? data?.citations ?? [])
  return items
    .map((item) => {
      const statement = item?.text_snippet ?? item?.statement ?? ''
      if (!statement) return null
      const status = String(item?.status ?? '').toLowerCase()
      return {
        key: item?.citation_id ?? item?.key ?? null,
        statement,
        evidenceRef: item?.evidence_id ?? item?.evidence_ref ?? item?.citation_id ?? null,
        pageOrSlide: item?.page_number ?? item?.page_or_slide ?? null,
        confidence: status === 'exact' ? 1 : status === 'approximate' ? 0.7 : null,
        metadata: {
          courseId,
          citationId: item?.citation_id ?? null,
          sourceStatus: status || null,
          sourceFile: item?.source_file ?? null,
          documentId: item?.document_id ?? null,
          renderUrl: item?.render_url ?? null,
          raw: item,
        },
      }
    })
    .filter(Boolean)
}

/**
 * Fetch teacher evidence spans from the course-scoped production API.
 * Students do not have ``evidence.review``; callers should only request this
 * in a teacher preview and treat a forbidden response as an empty evidence
 * list rather than hiding otherwise readable citations.
 */
export async function fetchCourseEvidenceSpans(courseId, options = {}) {
  if (courseId == null || courseId === '') return []
  const data = await request.get(
    `graph/course/${encodeURIComponent(courseId)}/evidence-spans`,
    { params: options },
  )
  const items = Array.isArray(data) ? data : (data?.items ?? data?.evidence_spans ?? [])
  return items.map((item) => parseEvidenceSpan({
    artifact_id: item?.span_id ?? item?.linked_evidence_id ?? item?.block_id,
    document_id: item?.document_id,
    block_id: item?.block_id ?? item?.span_id,
    page_or_slide: item?.page_number,
    char_start: item?.char_start,
    char_end: item?.char_end,
    text_snippet: item?.text_snippet,
    status: item?.status === 'stale' ? 'stale' : 'active',
    metadata: item,
  })).filter(Boolean)
}

// ---------------------------------------------------------------------------
// Evidence spans
// ---------------------------------------------------------------------------

/**
 * Fetch evidence spans for a document or a specific page.
 *
 * @param {string} documentId
 * @param {Object} [options]
 * @param {number} [options.page] - Filter to a specific page
 * @returns {Promise<Array>} Array of parsed EvidenceSpan objects
 */
export async function fetchEvidenceSpans(documentId, options = {}) {
  let url = `${API_BASE}/documents/${encodeURIComponent(documentId)}/evidence`
  if (options.page != null) {
    url += `?page=${options.page}`
  }
  const response = await evidenceFetch(url)
  const data = await response.json()
  const items = Array.isArray(data) ? data : (data.evidence_spans ?? [])
  return items.map(item => parseEvidenceSpan(item)).filter(Boolean)
}

/** Read the production Canonical DocumentIR anchor projection for one run. */
export async function fetchCanonicalEvidenceViewer(courseId, runId) {
  if (!courseId || !runId) throw new Error('courseId and runId are required')
  const data = await request.get(
    `graph/course/${encodeURIComponent(courseId)}/document-ir/${encodeURIComponent(runId)}/anchors`,
  )
  let rawCitations = []
  try {
    const citationData = await request.get(
      `graph/course/${encodeURIComponent(courseId)}/citations`,
      { params: { include_stale: true } },
    )
    rawCitations = citationData?.items ?? []
  } catch {
    // Keep the empty initial value when the optional citation projection is unavailable.
  }
  const citations = rawCitations
    .filter((citation) => !citation.run_id || citation.run_id === runId)
    .map((citation) => parseCitation({
      key: citation.citation_id,
      statement: citation.text_snippet,
      evidence_ref: citation.evidence_id ?? null,
      page_or_slide: citation.page_number,
      metadata: {
        course_id: citation.course_id,
        run_id: citation.run_id,
        document_id: citation.document_id,
        status: citation.status,
        source_file: citation.source_file,
        bbox: citation.bbox,
        source_anchor_ids: citation.source_anchor_ids ?? [],
      },
    }))
    .filter(Boolean)
  const pageAssets = Array.isArray(data.page_assets) ? data.page_assets : []
  const pages = new Map(pageAssets.map((page) => [Number(page.page_or_slide), page]))
  const evidenceSpans = (Array.isArray(data.items) ? data.items : []).map((anchor) => ({
    artifact_id: anchor.provenance?.artifact_id ?? anchor.ir_version_id,
    document_id: anchor.document_id,
    unit_id: anchor.unit_id,
    block_id: anchor.block_id,
    version_ref: anchor.ir_version_id,
    page_or_slide: anchor.page_or_slide,
    char_start: anchor.char_start,
    char_end: anchor.char_end,
    text_snippet: anchor.text,
    status: anchor.status === 'active' ? 'active' : (anchor.status === 'stale' ? 'stale' : 'suspended'),
    metadata: anchor.bbox ? { bboxes: [anchor.bbox] } : {},
  })).map((anchor) => parseEvidenceSpan(anchor)).filter(Boolean)
  const maxPage = Math.max(0, ...pageAssets.map((page) => Number(page.page_or_slide) || 0))
  return {
    runId: data.run_id ?? runId,
    documentId: data.items?.[0]?.document_id ?? '',
    citations,
    evidenceSpans,
    pageImageUrls: Array.from({ length: maxPage }, (_, index) => pages.get(index + 1)?.rendition_url ?? null),
  }
}

// ---------------------------------------------------------------------------
// Citation validation
// ---------------------------------------------------------------------------

/**
 * Validate citations against evidence.
 *
 * @param {string} documentId
 * @param {Array<Object>} citations - Citation objects to validate
 * @returns {Promise<Object>} Parsed CitationValidationResult
 */
export async function validateCitations(documentId, citations) {
  const url = `${API_BASE}/documents/${encodeURIComponent(documentId)}/citations/validate`
  const response = await evidenceFetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ citations }),
  })
  const data = await response.json()
  return parseCitationValidationResult(data)
}

// ---------------------------------------------------------------------------
// Utility: check evidence staleness
// ---------------------------------------------------------------------------

/**
 * Check if any evidence spans in a list have a stale status.
 *
 * @param {Array} evidenceSpans - Array of parsed EvidenceSpan objects
 * @returns {boolean}
 */
export function hasStaleEvidence(evidenceSpans) {
  return Array.isArray(evidenceSpans) &&
    evidenceSpans.some(es => es.status === EvidenceStatus.STALE)
}

/**
 * Get only active (non-stale, non-suspended) evidence spans.
 *
 * @param {Array} evidenceSpans
 * @returns {Array}
 */
export function getActiveEvidence(evidenceSpans) {
  if (!Array.isArray(evidenceSpans)) return []
  return evidenceSpans.filter(es => es.status === EvidenceStatus.ACTIVE)
}
