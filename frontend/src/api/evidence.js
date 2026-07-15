/**
 * P1-04 Evidence API module.
 *
 * Provides functions to fetch document page images, citations, and evidence
 * data from the backend. This module is consumed by P1-04 components only.
 * P1-09 owns the actual mounting of these API calls into the production
 * request pipeline.
 *
 * For G2 isolated development, this module returns fixture data when
 * the backend is unavailable. P1-09 replaces this with real API calls
 * at G3 integration.
 *
 * RISK-02: All API responses are validated through the contracts module
 * before being passed to viewer components. Invalid or stale data is
 * explicitly flagged rather than silently displayed.
 */

import {
  parseCitation,
  parseEvidenceSpan,
  parseCitationValidationResult,
  CitationStatus,
  EvidenceStatus,
} from '../features/evidence-viewer/contracts.js'

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
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`Failed to fetch page image: ${response.status}`)
  }
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
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`Failed to fetch document pages: ${response.status}`)
  }
  const data = await response.json()
  return Array.isArray(data) ? data : (data.pages ?? [])
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
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`Failed to fetch citations: ${response.status}`)
  }
  const data = await response.json()
  const items = Array.isArray(data) ? data : (data.citations ?? [])
  return items.map(item => parseCitation(item)).filter(Boolean)
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
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`Failed to fetch evidence spans: ${response.status}`)
  }
  const data = await response.json()
  const items = Array.isArray(data) ? data : (data.evidence_spans ?? [])
  return items.map(item => parseEvidenceSpan(item)).filter(Boolean)
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
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ citations }),
  })
  if (!response.ok) {
    throw new Error(`Failed to validate citations: ${response.status}`)
  }
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
