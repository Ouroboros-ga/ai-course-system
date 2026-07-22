/**
 * Graph Browser feature contracts (P1-09 contract discipline, frozen).
 *
 * Implements the report discipline "schema versioning + fail-closed" for the
 * graph visualization payload. Mirrors the evidence-viewer contract style.
 *
 * - ``graph-browser/1.0`` is the ONLY accepted major version (frozen).
 * - Unknown major versions MUST be rejected (fail-closed).
 * - Nodes/edges that fail validation are dropped (never fabricated).
 *
 * The graph is assembled on the client from REAL endpoints only:
 *   - course / knowledge-point structure  <- GET /api/v1/mapping/{course_id}
 *   - evidence spans / citations          <- /api/v1/evidence-v2 (V2, flag-gated)
 * No dense/vector/rerank/graph-traversal stages are fabricated. If a layer has
 * no real interface yet (e.g. graph relations / impact analysis), it is shown
 * as an explicit empty state, not faked.
 */

export const GRAPH_BROWSER_SCHEMA_VERSION = 'graph-browser/1.0'
export const FROZEN_MAJOR = '1.0'

/** Assert the schema version is compatible. Throws on unknown major. */
export function assertGraphBrowserSchema(version) {
  if (typeof version !== 'string') {
    throw new Error(`Graph browser schema version must be a string, got ${typeof version}`)
  }
  const major = version.split('/')[1]?.split('.')[0]
  if (version.split('/')[0] !== 'graph-browser' || major !== FROZEN_MAJOR) {
    throw new Error(
      `Unknown graph browser schema version "${version}". ` +
      `Frozen major is ${FROZEN_MAJOR}; fail-closed.`
    )
  }
  return true
}

/** Validate a graph node. Returns a normalized node or null (dropped). */
export function parseGraphNode(raw) {
  if (!raw || typeof raw !== 'object') return null
  const id = raw.id
  const kind = raw.kind
  if (!id || typeof id !== 'string') return null
  if (!['course', 'knowledge_point', 'evidence'].includes(kind)) return null
  return {
    id,
    kind,
    label: typeof raw.label === 'string' && raw.label ? raw.label : '(未命名)',
    // Optional metadata — explicitly optional, may be absent (never fabricated).
    documentId: raw.documentId != null ? String(raw.documentId) : null,
    spanId: raw.spanId != null ? String(raw.spanId) : null,
    citationCount: Number.isFinite(raw.citationCount) ? raw.citationCount : 0,
    pageStart: Number.isFinite(raw.pageStart) ? raw.pageStart : null,
    pageEnd: Number.isFinite(raw.pageEnd) ? raw.pageEnd : null,
    confidence: Number.isFinite(raw.confidence) ? raw.confidence : null,
    isManual: raw.isManual === true,
  }
}

/** Validate a graph edge. Returns a normalized edge or null (dropped). */
export function parseGraphEdge(raw) {
  if (!raw || typeof raw !== 'object') return null
  const source = raw.source
  const target = raw.target
  const kind = raw.kind
  if (!source || !target || typeof source !== 'string' || typeof target !== 'string') return null
  if (!['contains', 'has_evidence'].includes(kind)) return null
  return { source, target, kind }
}
