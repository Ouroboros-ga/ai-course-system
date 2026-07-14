/**
 * P1-04 Evidence Viewer — Frontend contract types.
 *
 * Mirrors the frozen back-end contracts consumed from P1-01 (Geometry)
 * and P1-03 (Evidence/Citation) for use in the isolated frontend feature.
 *
 * Geometry contract (P1-01, frozen-major, document-ir/1.0):
 *   - BoundingBox, Polygon, CoordinateSpace
 *
 * Evidence/Citation contract (P1-03, frozen-major, evidence/1.0, citation/1.0):
 *   - EvidenceSpan, EvidenceBundle, EvidenceStatus
 *   - Citation, CitationValidationResult, CitationStatus
 *
 * These are frontend-native representations. The back-end will serialise
 * its frozen dataclasses to JSON; the frontend deserialises them here.
 * Unknown major versions must be rejected (fail-closed).
 */

// =============================================================================
// Coordinate Space (from P1-01 Geometry)
// =============================================================================

/** @readonly */
export const CoordinateSpace = Object.freeze({
  NORMALIZED: 'normalized',
  INCH: 'inch',
  MILLIMETER: 'millimeter',
  POINT: 'point',
  PIXEL: 'pixel',
  EMU: 'emu',
})

// =============================================================================
// Geometry (from P1-01 Geometry)
// =============================================================================

/**
 * @typedef {Object} BoundingBox
 * @property {number} x0
 * @property {number} y0
 * @property {number} x1
 * @property {number} y1
 * @property {string} coordinateSpace - One of CoordinateSpace values
 */

/**
 * Create a validated BoundingBox from a plain object (JSON deserialisation).
 * Returns null for invalid data (fail-closed on malformed input).
 *
 * @param {Object} raw - Raw JSON object
 * @returns {BoundingBox|null}
 */
export function parseBoundingBox(raw) {
  if (!raw || typeof raw !== 'object') return null
  const x0 = Number(raw.x0)
  const y0 = Number(raw.y0)
  const x1 = Number(raw.x1)
  const y1 = Number(raw.y1)
  if (!isFinite(x0) || !isFinite(y0) || !isFinite(x1) || !isFinite(y1)) return null
  if (x0 > x1 || y0 > y1) return null

  const cs = raw.coordinate_space || raw.coordinateSpace || 'normalized'
  if (cs === 'normalized') {
    if (x0 < 0 || x0 > 1 || y0 < 0 || y0 > 1 || x1 < 0 || x1 > 1 || y1 < 0 || y1 > 1) return null
  }

  return { x0, y0, x1, y1, coordinateSpace: cs }
}

/**
 * @typedef {Object} Polygon
 * @property {Array<[number,number]>} points - At least 3 vertices
 * @property {string} coordinateSpace
 */

/**
 * Create a validated Polygon from a plain object.
 * Returns null for invalid data.
 *
 * @param {Object} raw
 * @returns {Polygon|null}
 */
export function parsePolygon(raw) {
  if (!raw || typeof raw !== 'object') return null
  let pts = raw.points
  if (!Array.isArray(pts)) return null
  if (pts.length < 3) return null

  const cs = raw.coordinate_space || raw.coordinateSpace || 'normalized'
  const parsed = pts.map((p, i) => {
    if (!Array.isArray(p) || p.length < 2) return null
    const x = Number(p[0])
    const y = Number(p[1])
    if (!isFinite(x) || !isFinite(y)) return null
    if (cs === 'normalized' && (x < 0 || x > 1 || y < 0 || y > 1)) return null
    return [x, y]
  })
  if (parsed.some(p => p === null)) return null

  return { points: parsed, coordinateSpace: cs }
}

/**
 * Compute the axis-aligned bounding box of a polygon.
 * @param {Polygon} polygon
 * @returns {BoundingBox}
 */
export function polygonToBBox(polygon) {
  const xs = polygon.points.map(p => p[0])
  const ys = polygon.points.map(p => p[1])
  return {
    x0: Math.min(...xs),
    y0: Math.min(...ys),
    x1: Math.max(...xs),
    y1: Math.max(...ys),
    coordinateSpace: polygon.coordinateSpace,
  }
}

// =============================================================================
// Evidence Status (from P1-03 Evidence)
// =============================================================================

/** @readonly */
export const EvidenceStatus = Object.freeze({
  ACTIVE: 'active',
  STALE: 'stale',
  SUSPENDED: 'suspended',
})

// =============================================================================
// Citation Status (from P1-03 Citation)
// =============================================================================

/** @readonly */
export const CitationStatus = Object.freeze({
  VERIFIED: 'verified',
  PARTIAL: 'partial',
  MISMATCH: 'mismatch',
  STALE: 'stale',
  NO_EVIDENCE: 'no_evidence',
})

// =============================================================================
// EvidenceSpan (from P1-03 Evidence)
// =============================================================================

/**
 * @typedef {Object} EvidenceSpan
 * @property {string} artifactId
 * @property {string} documentId
 * @property {string} unitId
 * @property {string} blockId
 * @property {string|null} versionRef
 * @property {number|null} pageOrSlide
 * @property {number|null} charStart
 * @property {number|null} charEnd
 * @property {string|null} textSnippet
 * @property {number|null} score
 * @property {string} status - One of EvidenceStatus values
 * @property {Object} metadata
 */

/**
 * Parse an EvidenceSpan from a JSON response (snake_case or camelCase keys).
 * Returns null for invalid input (fail-closed).
 *
 * @param {Object} raw
 * @returns {EvidenceSpan|null}
 */
export function parseEvidenceSpan(raw) {
  if (!raw || typeof raw !== 'object') return null
  if (!raw.artifact_id && !raw.artifactId) return null
  if (!raw.block_id && !raw.blockId) return null

  return {
    artifactId: raw.artifact_id ?? raw.artifactId ?? '',
    documentId: raw.document_id ?? raw.documentId ?? '',
    unitId: raw.unit_id ?? raw.unitId ?? '',
    blockId: raw.block_id ?? raw.blockId ?? '',
    versionRef: raw.version_ref ?? raw.versionRef ?? null,
    pageOrSlide: raw.page_or_slide ?? raw.pageOrSlide ?? null,
    charStart: raw.char_start ?? raw.charStart ?? null,
    charEnd: raw.char_end ?? raw.charEnd ?? null,
    textSnippet: raw.text_snippet ?? raw.textSnippet ?? null,
    score: raw.score ?? null,
    status: raw.status ?? 'active',
    metadata: raw.metadata ?? {},
  }
}

// =============================================================================
// Citation (from P1-03 Citation)
// =============================================================================

/**
 * @typedef {Object} Citation
 * @property {string|null} key
 * @property {string} statement
 * @property {string|null} evidenceRef
 * @property {number|null} pageOrSlide
 * @property {number|null} confidence
 * @property {Object} metadata
 */

/**
 * Parse a Citation from JSON.
 * @param {Object} raw
 * @returns {Citation|null}
 */
export function parseCitation(raw) {
  if (!raw || typeof raw !== 'object') return null
  if (!raw.key && raw.key !== null) return null // key must be string or null
  if (!raw.statement) return null

  return {
    key: raw.key ?? null,
    statement: raw.statement,
    evidenceRef: raw.evidence_ref ?? raw.evidenceRef ?? null,
    pageOrSlide: raw.page_or_slide ?? raw.pageOrSlide ?? null,
    confidence: raw.confidence ?? null,
    metadata: raw.metadata ?? {},
  }
}

// =============================================================================
// CitationValidationResult (from P1-03 Citation)
// =============================================================================

/**
 * @typedef {Object} CitationValidationResult
 * @property {string} status
 * @property {boolean} abstain
 * @property {string|null} abstainReason
 * @property {Array<Object>} details
 * @property {number} verifiedCount
 * @property {number} totalCount
 */

/**
 * Parse CitationValidationResult from JSON.
 * @param {Object} raw
 * @returns {CitationValidationResult|null}
 */
export function parseCitationValidationResult(raw) {
  if (!raw || typeof raw !== 'object') return null
  if (!raw.status) return null
  return {
    status: raw.status,
    abstain: !!raw.abstain,
    abstainReason: raw.abstain_reason ?? raw.abstainReason ?? null,
    details: Array.isArray(raw.details) ? raw.details : [],
    verifiedCount: raw.verified_count ?? raw.verifiedCount ?? 0,
    totalCount: raw.total_count ?? raw.totalCount ?? 0,
  }
}

// =============================================================================
// EvidenceViewer props (P1-04 downstream contract)
// =============================================================================

/**
 * @typedef {Object} EvidenceViewerProps
 * @property {string} documentId - Stable document ID
 * @property {string} artifactId - Stable artifact ID
 * @property {Array<Citation>} citations - Citations to display
 * @property {Array<EvidenceSpan>} evidenceSpans - Evidence spans for highlighting
 * @property {Array<string>} pageImageUrls - URLs to rendered page images
 * @property {number} totalPages - Total pages in document
 * @property {number|null} initialPage - Page to start on (1-based)
 * @property {number} initialZoom - Zoom level (1.0 = 100%)
 * @property {number} initialRotation - Rotation in degrees (0/90/180/270)
 * @property {boolean} readOnly - Whether user can interact with highlights
 */

/**
 * Default EvidenceViewer props.
 */
export const DEFAULT_VIEWER_PROPS = Object.freeze({
  documentId: '',
  artifactId: '',
  citations: [],
  evidenceSpans: [],
  pageImageUrls: [],
  totalPages: 0,
  initialPage: 1,
  initialZoom: 1.0,
  initialRotation: 0,
  readOnly: false,
})
