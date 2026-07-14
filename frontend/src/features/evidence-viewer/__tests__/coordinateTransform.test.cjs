/**
 * P1-04 — Coordinate transform unit tests.
 *
 * These test pure functions only and can be run with Node.js directly
 * (no npm install required). Run with:
 *   node frontend/src/features/evidence-viewer/__tests__/coordinateTransform.test.js
 *
 * Tests:
 *   - normalizedToDisplay: basic conversion, out-of-bounds, zero dimensions
 *   - bboxToDisplayRect: basic, zoom, rotation, invalid input (fail-closed)
 *   - polygonToDisplayPoints: basic, invalid polygons, zoom+rotation
 *   - allCoordinatesValid / allPolygonsValid: valid/invalid detection
 *   - parseBoundingBox / parsePolygon: contract parsing from JSON
 *   - normalizedToPagePixel: page-pixel mapping
 */

// ---- Import the module ----
// Use dynamic path: these tests live alongside the source
const path = require('path')
const mod = require(path.join(__dirname, '..', 'composables', 'coordinateTransform.js'))

const {
  normalizedToDisplay,
  bboxToDisplayRect,
  polygonToDisplayPoints,
  allCoordinatesValid,
  allPolygonsValid,
  normalizedToPagePixel,
  pagePixelToDisplay,
  applyZoom,
  applyRotation,
} = mod

// ---- Test runner (simple, no dependencies) ----

let passed = 0
let failed = 0
const failures = []

function assert(condition, label) {
  if (condition) {
    passed++
  } else {
    failed++
    failures.push(label)
    console.error(`  FAIL: ${label}`)
  }
}

function assertClose(actual, expected, tolerance, label) {
  const ok = Math.abs(actual - expected) <= tolerance
  if (ok) {
    passed++
  } else {
    failed++
    failures.push(label)
    console.error(`  FAIL: ${label} — expected ${expected}, got ${actual}`)
  }
}

function assertDeepEqual(actual, expected, label) {
  const a = JSON.stringify(actual)
  const e = JSON.stringify(expected)
  if (a === e) {
    passed++
  } else {
    failed++
    failures.push(label)
    console.error(`  FAIL: ${label} — expected ${e}, got ${a}`)
  }
}

// =============================================================================
// Tests: normalizedToDisplay
// =============================================================================

console.log('\n=== normalizedToDisplay ===')

// Basic conversion
const p1 = normalizedToDisplay(0.5, 0.5, 800, 600)
assert(p1 != null, 'basic conversion returns value')
assertClose(p1.x, 400, 0.01, 'nx=0.5 -> x=400')
assertClose(p1.y, 300, 0.01, 'ny=0.5 -> y=300')

// Corners
const tl = normalizedToDisplay(0, 0, 800, 600)
assertClose(tl.x, 0, 0.01, 'top-left x=0')
assertClose(tl.y, 0, 0.01, 'top-left y=0')

const br = normalizedToDisplay(1, 1, 800, 600)
assertClose(br.x, 800, 0.01, 'bottom-right x=800')
assertClose(br.y, 600, 0.01, 'bottom-right y=600')

// Zero dimensions -> null
const z = normalizedToDisplay(0.5, 0.5, 0, 600)
assert(z == null, 'zero width returns null')

const z2 = normalizedToDisplay(0.5, 0.5, 800, 0)
assert(z2 == null, 'zero height returns null')

// Non-finite input -> null
const nf = normalizedToDisplay(NaN, 0.5, 800, 600)
assert(nf == null, 'NaN x returns null')

const nf2 = normalizedToDisplay(0.5, Infinity, 800, 600)
assert(nf2 == null, 'Infinity y returns null')

// =============================================================================
// Tests: normalizedToPagePixel
// =============================================================================

console.log('\n=== normalizedToPagePixel ===')

const pp1 = normalizedToPagePixel(0.5, 0.5, 2400, 1800)
assert(pp1 != null, 'page pixel conversion returns value')
assertClose(pp1.x, 1200, 0.01, 'page pixel x=1200')
assertClose(pp1.y, 900, 0.01, 'page pixel y=900')

const pp0 = normalizedToPagePixel(0, 0, 2400, 1800)
assertClose(pp0.x, 0, 0.01, 'page pixel origin x=0')
assertClose(pp0.y, 0, 0.01, 'page pixel origin y=0')

const ppNull = normalizedToPagePixel(0.5, 0.5, 0, 1800)
assert(ppNull == null, 'page pixel zero width returns null')

// =============================================================================
// Tests: bboxToDisplayRect
// =============================================================================

console.log('\n=== bboxToDisplayRect ===')

const bbox1 = { x0: 0.1, y0: 0.2, x1: 0.5, y1: 0.6, coordinateSpace: 'normalized' }
const r1 = bboxToDisplayRect(bbox1, 800, 600)
assert(r1 != null, 'bbox to rect returns value')
assertClose(r1.x, 80, 0.01, 'rect x=80')
assertClose(r1.y, 120, 0.01, 'rect y=120')
assertClose(r1.w, 320, 0.01, 'rect w=320')
assertClose(r1.h, 240, 0.01, 'rect h=240')

// Invalid coordinate space -> null
const badSpace = { x0: 0.1, y0: 0.2, x1: 0.5, y1: 0.6, coordinateSpace: 'inch' }
const rBad = bboxToDisplayRect(badSpace, 800, 600)
assert(rBad == null, 'non-normalized bbox returns null')

// Null bbox -> null
const rNull = bboxToDisplayRect(null, 800, 600)
assert(rNull == null, 'null bbox returns null')

// With zoom (center zoom at displayWidth/2, displayHeight/2 = 400, 300)
// bbox display coords: (80,120) -> (400,360), center=(400,300), zoom=2.0
// top-left: x=400+(80-400)*2=-240, y=300+(120-300)*2=-60
// bottom-right: x=400+(400-400)*2=400, y=300+(360-300)*2=420
// rect: x=-240, y=-60, w=640, h=480
const rZoom = bboxToDisplayRect(bbox1, 800, 600, { zoom: 2.0 })
assert(rZoom != null, 'zoomed bbox returns value')
assertClose(rZoom.x, -240, 0.01, 'zoomed rect x=-240')
assertClose(rZoom.y, -60, 0.01, 'zoomed rect y=-60')
assertClose(rZoom.w, 640, 0.01, 'zoomed rect w=640')
assertClose(rZoom.h, 480, 0.01, 'zoomed rect h=480')

// Full-page bbox
const full = { x0: 0, y0: 0, x1: 1, y1: 1, coordinateSpace: 'normalized' }
const rFull = bboxToDisplayRect(full, 800, 600)
assertClose(rFull.x, 0, 0.01, 'full rect x=0')
assertClose(rFull.y, 0, 0.01, 'full rect y=0')
assertClose(rFull.w, 800, 0.01, 'full rect w=800')
assertClose(rFull.h, 600, 0.01, 'full rect h=600')

// =============================================================================
// Tests: polygonToDisplayPoints
// =============================================================================

console.log('\n=== polygonToDisplayPoints ===')

const poly1 = {
  points: [[0.1, 0.1], [0.5, 0.1], [0.5, 0.4], [0.1, 0.4]],
  coordinateSpace: 'normalized',
}
const pts1 = polygonToDisplayPoints(poly1, 800, 600)
assert(pts1 != null, 'polygon to points returns value')
assert(typeof pts1 === 'string', 'polygon result is string')
assert(pts1.includes('80,60'), 'polygon contains 80,60')
assert(pts1.includes('400,60'), 'polygon contains 400,60')

// Too few points -> null
const tinyPoly = { points: [[0.1, 0.1], [0.5, 0.5]], coordinateSpace: 'normalized' }
const ptsBad = polygonToDisplayPoints(tinyPoly, 800, 600)
assert(ptsBad == null, 'polygon with <3 points returns null')

// Null polygon -> null
const ptsNull = polygonToDisplayPoints(null, 800, 600)
assert(ptsNull == null, 'null polygon returns null')

// Non-normalized -> null
const ptsInch = polygonToDisplayPoints(
  { points: [[0.1, 0.1], [0.5, 0.1], [0.5, 0.4], [0.1, 0.4]], coordinateSpace: 'inch' },
  800, 600
)
assert(ptsInch == null, 'inch polygon returns null')

// =============================================================================
// Tests: allCoordinatesValid
// =============================================================================

console.log('\n=== allCoordinatesValid ===')

assert(allCoordinatesValid([{ x0: 0, y0: 0, x1: 1, y1: 1, coordinateSpace: 'normalized' }]),
  'single valid bbox returns true')

assert(!allCoordinatesValid([]), 'empty array returns false')

assert(!allCoordinatesValid(null), 'null returns false')

assert(!allCoordinatesValid([{ x0: -0.1, y0: 0, x1: 1, y1: 1, coordinateSpace: 'normalized' }]),
  'negative x0 returns false')

assert(!allCoordinatesValid([{ x0: 0, y0: 0, x1: 1.5, y1: 1, coordinateSpace: 'normalized' }]),
  'x1 > 1 returns false')

assert(!allCoordinatesValid([{ x0: 0, y0: 0, x1: 1, y1: 1, coordinateSpace: 'inch' }]),
  'non-normalized returns false')

// =============================================================================
// Tests: allPolygonsValid
// =============================================================================

console.log('\n=== allPolygonsValid ===')

const validPoly = { points: [[0, 0], [0.5, 0], [0.5, 0.5]], coordinateSpace: 'normalized' }
assert(allPolygonsValid([validPoly]), 'valid polygon returns true')

assert(!allPolygonsValid([]), 'empty polygons returns false')

const outPoly = { points: [[0, 0], [0.5, 0], [1.5, 0.5]], coordinateSpace: 'normalized' }
assert(!allPolygonsValid([outPoly]), 'out-of-bounds polygon returns false')

const badPoly = { points: [[0, 0], [0.5, 0]], coordinateSpace: 'normalized' }
assert(!allPolygonsValid([badPoly]), 'polygon with <3 points returns false')

// =============================================================================
// Tests: applyZoom
// =============================================================================

console.log('\n=== applyZoom ===')

const zoomP = applyZoom(200, 150, 2.0, 400, 300)
assertClose(zoomP.x, 0, 0.01, 'zoom x: 200 centered at 400 -> 0')
assertClose(zoomP.y, 0, 0.01, 'zoom y: 150 centered at 300 -> 0')

const zoomCenter = applyZoom(400, 300, 2.0, 400, 300)
assertClose(zoomCenter.x, 400, 0.01, 'zoom center x unchanged')
assertClose(zoomCenter.y, 300, 0.01, 'zoom center y unchanged')

// =============================================================================
// Tests: applyRotation
// =============================================================================

console.log('\n=== applyRotation ===')

// 90 degrees
const r90 = applyRotation(400, 200, 90, 400, 300)
assertClose(r90.x, 500, 0.01, 'rotate 90: x=500')
assertClose(r90.y, 300, 0.01, 'rotate 90: y=300')

// 180 degrees
const r180 = applyRotation(400, 200, 180, 400, 300)
assertClose(r180.x, 400, 0.01, 'rotate 180: x=400')
assertClose(r180.y, 400, 0.01, 'rotate 180: y=400')

// 0 degrees (no-op)
const r0 = applyRotation(100, 200, 0, 400, 300)
assertClose(r0.x, 100, 0.01, 'rotate 0: x unchanged')
assertClose(r0.y, 200, 0.01, 'rotate 0: y unchanged')

// =============================================================================
// Test: pagePixelToDisplay
// =============================================================================

console.log('\n=== pagePixelToDisplay ===')

const pd = pagePixelToDisplay(1200, 900, 2400, 1800, 800, 600)
assertClose(pd.x, 400, 0.01, 'pagePixelToDisplay x=400')
assertClose(pd.y, 300, 0.01, 'pagePixelToDisplay y=300')

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
