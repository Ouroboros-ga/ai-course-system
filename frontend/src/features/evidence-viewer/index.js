/**
 * P1-04 Evidence Viewer — barrel exports.
 *
 * Consumer components (P1-09) can import from this single entry point:
 *   import { EvidenceViewer, EvidenceViewerWithPanel } from '@/features/evidence-viewer'
 */

export { default as EvidenceViewer } from './components/EvidenceViewer.vue'
export { default as EvidenceViewerWithPanel } from './components/EvidenceViewerWithPanel.vue'
export { default as CitationPanel } from './components/CitationPanel.vue'
export { default as CitationCard } from './components/CitationCard.vue'
export { default as PageViewer } from './components/PageViewer.vue'
export { default as HighlightOverlay } from './components/HighlightOverlay.vue'
export { default as StatusIndicator } from './components/StatusIndicator.vue'

export { useViewer } from './composables/useViewer.js'
export {
  normalizedToDisplay,
  normalizedToPagePixel,
  pagePixelToDisplay,
  bboxToDisplayRect,
  polygonToDisplayPoints,
  applyZoom,
  applyRotation,
  allCoordinatesValid,
  allPolygonsValid,
} from './composables/coordinateTransform.js'

export {
  parseBoundingBox,
  parsePolygon,
  polygonToBBox,
  parseEvidenceSpan,
  parseCitation,
  parseCitationValidationResult,
  CoordinateSpace,
  EvidenceStatus,
  CitationStatus,
  DEFAULT_VIEWER_PROPS,
} from './contracts.js'
