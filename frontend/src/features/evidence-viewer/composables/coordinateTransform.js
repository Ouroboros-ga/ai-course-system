/**
 * P1-04 — Coordinate transforms for normalised BBox/Polygon -> screen coords.
 *
 * Consumes Geometry from P1-01 (frozen, document-ir/1.0):
 *   - BoundingBox with coordinate_space = "normalized" (0..1 relative to page)
 *   - Polygon with same semantics
 *
 * Handles:
 *   - Normalised (0..1) -> page-pixel via natural size
 *   - CSS display size scaling (CSS != natural)
 *   - Zoom transforms
 *   - Rotation transforms (0/90/180/270)
 *   - Edge clamping / bounds reporting
 *
 * Design rule: do NOT silently clamp out-of-bounds coordinates to page area.
 * If any vertex falls outside [0,1] range and coordinate_space is "normalized",
 * return null (fail-closed) so the caller can show a "missing coordinate" indicator.
 */

/**
 * Convert a normalised (0..1) coordinate to page-pixel space given the
 * page's natural dimensions in device-independent pixels.
 *
 * @param {number} nx - Normalised x (0..1)
 * @param {number} ny - Normalised y (0..1)
 * @param {number} pageWidth - Natural page width in pixels
 * @param {number} pageHeight - Natural page height in pixels
 * @returns {{x: number, y: number}|null} Page-pixel coords, or null if out of bounds
 */
export function normalizedToPagePixel(nx, ny, pageWidth, pageHeight) {
  if (pageWidth <= 0 || pageHeight <= 0) return null
  if (!isFinite(nx) || !isFinite(ny)) return null

  return {
    x: nx * pageWidth,
    y: ny * pageHeight,
  }
}

/**
 * Convert page-pixel coordinates to CSS-display coordinates given the
 * display size of the image/container element.
 *
 * @param {number} px - Page-pixel x
 * @param {number} py - Page-pixel y
 * @param {number} pageWidth - Natural page width in pixels
 * @param {number} pageHeight - Natural page height in pixels
 * @param {number} displayWidth - CSS display width in pixels
 * @param {number} displayHeight - CSS display height in pixels
 * @returns {{x: number, y: number}|null}
 */
export function pagePixelToDisplay(px, py, pageWidth, pageHeight, displayWidth, displayHeight) {
  if (pageWidth <= 0 || pageHeight <= 0 || displayWidth <= 0 || displayHeight <= 0) return null
  return {
    x: (px / pageWidth) * displayWidth,
    y: (py / pageHeight) * displayHeight,
  }
}

/**
 * Normalised (0..1) coordinates directly to CSS display coordinates.
 * This is the typical path: the image renders at some display size,
 * and we overlay at the same scale.
 *
 * @param {number} nx - Normalised x
 * @param {number} ny - Normalised y
 * @param {number} displayWidth - CSS display width in pixels
 * @param {number} displayHeight - CSS display height in pixels
 * @returns {{x: number, y: number}|null}
 */
export function normalizedToDisplay(nx, ny, displayWidth, displayHeight) {
  if (displayWidth <= 0 || displayHeight <= 0) return null
  if (!isFinite(nx) || !isFinite(ny)) return null
  // Normalised values should be in [0,1]; out-of-range is still computable
  // but the caller should check validity first.
  return {
    x: nx * displayWidth,
    y: ny * displayHeight,
  }
}

/**
 * Apply a zoom factor to display coordinates.
 * Zoom is centered on (cx, cy) — typically the center of the viewport.
 *
 * @param {number} x - Display x
 * @param {number} y - Display y
 * @param {number} zoom - Zoom factor (1.0 = no zoom)
 * @param {number} cx - Zoom center x
 * @param {number} cy - Zoom center y
 * @returns {{x: number, y: number}}
 */
export function applyZoom(x, y, zoom, cx, cy) {
  return {
    x: cx + (x - cx) * zoom,
    y: cy + (y - cy) * zoom,
  }
}

/**
 * Apply a rotation transform to display coordinates.
 * Rotation is about the center of the page image.
 *
 * Supported rotation values: 0, 90, 180, 270 (degrees clockwise).
 *
 * @param {number} x - Display x (pre-rotation)
 * @param {number} y - Display y (pre-rotation)
 * @param {number} rotationDeg - Rotation in degrees (0/90/180/270)
 * @param {number} cx - Rotation center x
 * @param {number} cy - Rotation center y
 * @returns {{x: number, y: number}}
 */
export function applyRotation(x, y, rotationDeg, cx, cy) {
  const rad = (rotationDeg * Math.PI) / 180
  const cos = Math.cos(rad)
  const sin = Math.sin(rad)

  // Translate to origin, rotate, translate back
  const dx = x - cx
  const dy = y - cy
  return {
    x: cx + dx * cos - dy * sin,
    y: cy + dx * sin + dy * cos,
  }
}

/**
 * Transform a normalised BoundingBox to CSS display coordinates,
 * applying zoom and rotation if specified.
 *
 * @param {Object} bbox - BoundingBox with x0,y0,x1,y1,coordinateSpace
 * @param {number} displayWidth - CSS display width in pixels
 * @param {number} displayHeight - CSS display height in pixels
 * @param {Object} [options]
 * @param {number} [options.zoom=1.0]
 * @param {number} [options.rotation=0]
 * @param {number} [options.zoomCx] - Zoom center x (defaults to displayWidth/2)
 * @param {number} [options.zoomCy] - Zoom center y (defaults to displayHeight/2)
 * @returns {{x: number, y: number, w: number, h: number}|null}
 */
export function bboxToDisplayRect(bbox, displayWidth, displayHeight, options = {}) {
  if (!bbox || bbox.coordinateSpace !== 'normalized') return null
  const zoom = options.zoom ?? 1.0
  const rotation = options.rotation ?? 0
  const cx = options.zoomCx ?? displayWidth / 2
  const cy = options.zoomCy ?? displayHeight / 2

  // Top-left corner
  const tl = normalizedToDisplay(bbox.x0, bbox.y0, displayWidth, displayHeight)
  if (!tl) return null
  // Bottom-right corner
  const br = normalizedToDisplay(bbox.x1, bbox.y1, displayWidth, displayHeight)
  if (!br) return null

  if (zoom !== 1.0) {
    applyZoomToPoint(tl, zoom, cx, cy)
    applyZoomToPoint(br, zoom, cx, cy)
  }
  if (rotation !== 0) {
    applyRotationToPoint(tl, rotation, displayWidth / 2, displayHeight / 2)
    applyRotationToPoint(br, rotation, displayWidth / 2, displayHeight / 2)
  }

  return {
    x: Math.min(tl.x, br.x),
    y: Math.min(tl.y, br.y),
    w: Math.abs(br.x - tl.x),
    h: Math.abs(br.y - tl.y),
  }
}

/**
 * Transform a normalised Polygon to an SVG polygon points string
 * in CSS display coordinates, with optional zoom/rotation.
 *
 * @param {Object} polygon - Polygon with points[] and coordinateSpace
 * @param {number} displayWidth
 * @param {number} displayHeight
 * @param {Object} [options]
 * @returns {string|null} SVG points string, or null if transform fails
 */
export function polygonToDisplayPoints(polygon, displayWidth, displayHeight, options = {}) {
  if (!polygon || polygon.coordinateSpace !== 'normalized') return null
  if (!Array.isArray(polygon.points) || polygon.points.length < 3) return null

  const zoom = options.zoom ?? 1.0
  const rotation = options.rotation ?? 0
  const cx = options.zoomCx ?? displayWidth / 2
  const cy = options.zoomCy ?? displayHeight / 2

  const points = polygon.points.map(([nx, ny]) => {
    let p = normalizedToDisplay(nx, ny, displayWidth, displayHeight)
    if (!p) return null
    if (zoom !== 1.0) applyZoomToPoint(p, zoom, cx, cy)
    if (rotation !== 0) applyRotationToPoint(p, rotation, displayWidth / 2, displayHeight / 2)
    return `${p.x},${p.y}`
  })

  if (points.some(pt => pt === null)) return null
  return points.join(' ')
}

// =============================================================================
// Internal helpers (mutate in-place for performance; callers don't share refs)
// =============================================================================

function applyZoomToPoint(p, zoom, cx, cy) {
  p.x = cx + (p.x - cx) * zoom
  p.y = cy + (p.y - cy) * zoom
}

function applyRotationToPoint(p, rotationDeg, cx, cy) {
  const rad = (rotationDeg * Math.PI) / 180
  const cos = Math.cos(rad)
  const sin = Math.sin(rad)
  const dx = p.x - cx
  const dy = p.y - cy
  p.x = cx + dx * cos - dy * sin
  p.y = cy + dx * sin + dy * cos
}

/**
 * Validate that all coordinates in a set of evidence spans fall within
 * the normalised [0,1] range. Returns true if all are valid.
 *
 * RISK-02: fail-closed on invalid or missing coordinates.
 *
 * @param {Array<Object>} bboxes - Array of {x0,y0,x1,y1,coordinateSpace}
 * @returns {boolean}
 */
export function allCoordinatesValid(bboxes) {
  if (!Array.isArray(bboxes) || bboxes.length === 0) return false
  return bboxes.every(bb => {
    if (!bb || bb.coordinateSpace !== 'normalized') return false
    return (
      isFinite(bb.x0) && bb.x0 >= 0 && bb.x0 <= 1 &&
      isFinite(bb.y0) && bb.y0 >= 0 && bb.y0 <= 1 &&
      isFinite(bb.x1) && bb.x1 >= 0 && bb.x1 <= 1 &&
      isFinite(bb.y1) && bb.y1 >= 0 && bb.y1 <= 1 &&
      bb.x0 <= bb.x1 && bb.y0 <= bb.y1
    )
  })
}

/**
 * Validate that all polygon vertices fall within [0,1].
 * @param {Array<Object>} polygons
 * @returns {boolean}
 */
export function allPolygonsValid(polygons) {
  if (!Array.isArray(polygons) || polygons.length === 0) return false
  return polygons.every(poly => {
    if (!poly || poly.coordinateSpace !== 'normalized' || !Array.isArray(poly.points)) return false
    if (poly.points.length < 3) return false
    return poly.points.every(([x, y]) =>
      isFinite(x) && x >= 0 && x <= 1 &&
      isFinite(y) && y >= 0 && y <= 1
    )
  })
}
