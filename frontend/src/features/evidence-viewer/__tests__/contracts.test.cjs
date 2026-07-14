/**
 * P1-04 — Contract parsing unit tests.
 *
 * Tests the frontend contract types that mirror P1-01 Geometry and
 * P1-03 Evidence/Citation frozen contracts.
 *
 * Run with:
 *   node frontend/src/features/evidence-viewer/__tests__/contracts.test.js
 */

const path = require('path')
const mod = require(path.join(__dirname, '..', 'contracts.js'))

const {
  parseBoundingBox,
  parsePolygon,
  polygonToBBox,
  parseEvidenceSpan,
  parseCitation,
  parseCitationValidationResult,
  CoordinateSpace,
  EvidenceStatus,
  CitationStatus,
} = mod

// ---- Test runner ----

let passed = 0
let failed = 0
const failures = []

function assert(condition, label) {
  if (condition) { passed++ }
  else { failed++; failures.push(label); console.error(`  FAIL: ${label}`) }
}

function assertDeepEqual(actual, expected, label) {
  const a = JSON.stringify(actual)
  const e = JSON.stringify(expected)
  if (a === e) { passed++ }
  else { failed++; failures.push(label); console.error(`  FAIL: ${label} — expected ${e}, got ${a}`) }
}

// =============================================================================
// Tests: CoordinateSpace / EvidenceStatus / CitationStatus constants
// =============================================================================

console.log('\n=== Constants ===')

assert(CoordinateSpace.NORMALIZED === 'normalized', 'NORMALIZED constant')
assert(CoordinateSpace.INCH === 'inch', 'INCH constant')
assert(CoordinateSpace.PIXEL === 'pixel', 'PIXEL constant')
assert(EvidenceStatus.ACTIVE === 'active', 'ACTIVE status')
assert(EvidenceStatus.STALE === 'stale', 'STALE status')
assert(EvidenceStatus.SUSPENDED === 'suspended', 'SUSPENDED status')
assert(CitationStatus.VERIFIED === 'verified', 'VERIFIED status')
assert(CitationStatus.NO_EVIDENCE === 'no_evidence', 'NO_EVIDENCE status')

// =============================================================================
// Tests: parseBoundingBox
// =============================================================================

console.log('\n=== parseBoundingBox ===')

// Valid normalized bbox
const bb1 = parseBoundingBox({ x0: 0.1, y0: 0.2, x1: 0.8, y1: 0.9 })
assert(bb1 != null, 'valid bbox returns object')
assert(bb1.x0 === 0.1, 'bbox x0')
assert(bb1.y0 === 0.2, 'bbox y0')
assert(bb1.x1 === 0.8, 'bbox x1')
assert(bb1.y1 === 0.9, 'bbox y1')
assert(bb1.coordinateSpace === 'normalized', 'default coordinate space')

// Null input
assert(parseBoundingBox(null) == null, 'null bbox returns null')
assert(parseBoundingBox(undefined) == null, 'undefined bbox returns null')

// Invalid: x0 > x1
assert(parseBoundingBox({ x0: 0.8, y0: 0.2, x1: 0.1, y1: 0.9 }) == null, 'x0 > x1 returns null')

// Invalid: NaN
assert(parseBoundingBox({ x0: NaN, y0: 0.2, x1: 0.8, y1: 0.9 }) == null, 'NaN x0 returns null')

// Out of normalized range
assert(parseBoundingBox({ x0: -0.1, y0: 0, x1: 0.5, y1: 1 }) == null, 'negative normalized x0 returns null')
assert(parseBoundingBox({ x0: 0, y0: 0, x1: 1.5, y1: 1 }) == null, 'x1 > 1 returns null')

// Snake_case keys
const bbSnake = parseBoundingBox({ x0: 0.1, y0: 0.2, x1: 0.8, y1: 0.9, coordinate_space: 'normalized' })
assert(bbSnake != null, 'snake_case coordinate_space')

// camelCase keys
const bbCamel = parseBoundingBox({ x0: 0.1, y0: 0.2, x1: 0.8, y1: 0.9, coordinateSpace: 'normalized' })
assert(bbCamel != null, 'camelCase coordinateSpace')

// Non-normalized space (inch) — no range check
const bbInch = parseBoundingBox({ x0: 0.5, y0: 0.5, x1: 10, y1: 8, coordinate_space: 'inch' })
assert(bbInch != null, 'inch bbox is accepted')
assert(bbInch.coordinateSpace === 'inch', 'inch space preserved')

// =============================================================================
// Tests: parsePolygon
// =============================================================================

console.log('\n=== parsePolygon ===')

const poly1 = parsePolygon({ points: [[0.1, 0.1], [0.5, 0.1], [0.5, 0.4], [0.1, 0.4]] })
assert(poly1 != null, 'valid polygon returns object')
assert(poly1.points.length === 4, 'polygon has 4 points')
assert(poly1.coordinateSpace === 'normalized', 'polygon default space')

// Too few points
assert(parsePolygon({ points: [[0.1, 0.1], [0.5, 0.5]] }) == null, '<3 points returns null')

// Null
assert(parsePolygon(null) == null, 'null polygon returns null')
assert(parsePolygon(undefined) == null, 'undefined polygon returns null')

// NaN in points
assert(parsePolygon({ points: [[NaN, 0.1], [0.5, 0.1], [0.5, 0.4]] }) == null, 'NaN in points returns null')

// Out of bounds normalized
assert(parsePolygon({ points: [[-0.1, 0.1], [0.5, 0.1], [0.5, 0.4]] }) == null, 'negative normalized x returns null')

// =============================================================================
// Tests: polygonToBBox
// =============================================================================

console.log('\n=== polygonToBBox ===')

const pBBox = polygonToBBox({ points: [[0.1, 0.2], [0.8, 0.2], [0.8, 0.7], [0.1, 0.7]], coordinateSpace: 'normalized' })
assertDeepEqual(pBBox, { x0: 0.1, y0: 0.2, x1: 0.8, y1: 0.7, coordinateSpace: 'normalized' }, 'polygonToBBox correct')

// =============================================================================
// Tests: parseEvidenceSpan
// =============================================================================

console.log('\n=== parseEvidenceSpan ===')

const es1 = parseEvidenceSpan({
  artifact_id: 'art_001',
  document_id: 'doc_001',
  unit_id: 'unit_001',
  block_id: 'blk_001',
  status: 'active',
  page_or_slide: 1,
  text_snippet: 'sample text',
  score: 0.95,
})
assert(es1 != null, 'valid evidence span returns object')
assert(es1.artifactId === 'art_001', 'evidence artifactId')
assert(es1.blockId === 'blk_001', 'evidence blockId')
assert(es1.pageOrSlide === 1, 'evidence pageOrSlide')
assert(es1.status === 'active', 'evidence status')
assert(es1.score === 0.95, 'evidence score')

// camelCase keys
const esCamel = parseEvidenceSpan({
  artifactId: 'art_001',
  blockId: 'blk_001',
})
assert(esCamel != null, 'camelCase evidence span')

// Missing required fields
assert(parseEvidenceSpan(null) == null, 'null evidence returns null')
assert(parseEvidenceSpan({}) == null, 'empty evidence returns null')
assert(parseEvidenceSpan({ block_id: 'blk_001' }) == null, 'missing artifact_id returns null')
assert(parseEvidenceSpan({ artifact_id: 'art_001' }) == null, 'missing block_id returns null')

// STALE status
const esStale = parseEvidenceSpan({
  artifact_id: 'art_001',
  block_id: 'blk_001',
  status: 'stale',
})
assert(esStale != null, 'stale evidence parsed')
assert(esStale.status === 'stale', 'stale status preserved')

// =============================================================================
// Tests: parseCitation
// =============================================================================

console.log('\n=== parseCitation ===')

const cit1 = parseCitation({
  key: 'cit_abc123',
  statement: 'Some statement',
  page_or_slide: 3,
  confidence: 0.9,
})
assert(cit1 != null, 'valid citation returns object')
assert(cit1.key === 'cit_abc123', 'citation key')
assert(cit1.statement === 'Some statement', 'citation statement')
assert(cit1.pageOrSlide === 3, 'citation page')
assert(cit1.confidence === 0.9, 'citation confidence')

// camelCase
const citCamel = parseCitation({
  key: 'cit_abc',
  statement: 'Test',
  pageOrSlide: 1,
})
assert(citCamel != null, 'camelCase citation')

// Null key (no evidence)
const citNoKey = parseCitation({
  key: null,
  statement: 'Statement without evidence',
})
assert(citNoKey != null, 'citation with null key')
assert(citNoKey.key === null, 'null key preserved')

// Missing statement
assert(parseCitation({ key: 'cit_abc' }) == null, 'missing statement returns null')

// Null input
assert(parseCitation(null) == null, 'null citation returns null')

// =============================================================================
// Tests: parseCitationValidationResult
// =============================================================================

console.log('\n=== parseCitationValidationResult ===')

const vr1 = parseCitationValidationResult({
  status: 'verified',
  abstain: false,
  verified_count: 3,
  total_count: 3,
})
assert(vr1 != null, 'valid validation result')
assert(vr1.status === 'verified', 'validation status')
assert(vr1.abstain === false, 'not abstaining')
assert(vr1.verifiedCount === 3, 'verified count')
assert(vr1.totalCount === 3, 'total count')

// NO_EVIDENCE with abstain
const vrNoEv = parseCitationValidationResult({
  status: 'no_evidence',
  abstain: true,
  abstain_reason: 'No evidence provided',
  verified_count: 0,
  total_count: 1,
})
assert(vrNoEv != null, 'no_evidence result')
assert(vrNoEv.abstain === true, 'abstain true')
assert(vrNoEv.abstainReason === 'No evidence provided', 'abstain reason')

// Null input
assert(parseCitationValidationResult(null) == null, 'null validation returns null')

// =============================================================================
// Results
// =============================================================================

console.log('\n' + '='.repeat(50))
console.log(`Results: ${passed} passed, ${failed} failed`)
if (failed > 0) {
  console.log('\nFailures:')
  failures.forEach(f => console.log(`  - ${f}`))
  process.exit(1)
} else {
  console.log('All tests passed!')
}
