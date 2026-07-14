/**
 * P1-04 — Viewer state management composable.
 *
 * Manages the current page, zoom, rotation, highlighted regions,
 * and citation selection state for the evidence viewer.
 */

import { ref, computed, reactive } from 'vue'
import { EvidenceStatus } from '../contracts.js'

/**
 * Create a reactive viewer state.
 *
 * @param {Object} [options]
 * @param {number} [options.totalPages=0]
 * @param {number} [options.initialPage=1]
 * @param {number} [options.initialZoom=1.0]
 * @param {number} [options.initialRotation=0]
 * @returns {Object} Viewer state object
 */
export function useViewer(options = {}) {
  // ---- Reactive state ----

  const currentPage = ref(options.initialPage ?? 1)
  const totalPages = ref(options.totalPages ?? 0)
  const zoom = ref(options.initialZoom ?? 1.0)
  const rotation = ref(options.initialRotation ?? 0)
  const activeCitationKey = ref(null)
  const hoveredCitationKey = ref(null)

  /** @type {import('vue').Ref<Array>} */
  const citations = ref([])

  /** @type {import('vue').Ref<Array>} */
  const evidenceSpans = ref([])

  /** @type {import('vue').Ref<Array<string>>} */
  const pageImageUrls = ref([])

  /** Loading state per page */
  const loading = ref(false)

  /** Error state */
  const error = ref(null)

  // ---- Computed ----

  /** Current page's image URL (1-based index) */
  const currentPageImageUrl = computed(() => {
    const idx = currentPage.value - 1
    return pageImageUrls.value[idx] ?? null
  })

  /** Evidence spans for the current page */
  const currentPageEvidence = computed(() => {
    return evidenceSpans.value.filter(es => {
      const p = es.pageOrSlide
      return p == null || p === currentPage.value
    })
  })

  /** Evidence that has stale/suspended status */
  const staleEvidence = computed(() => {
    return evidenceSpans.value.filter(es =>
      es.status === EvidenceStatus.STALE || es.status === EvidenceStatus.SUSPENDED
    )
  })

  /** Active evidence for the current page */
  const currentPageActiveEvidence = computed(() => {
    return currentPageEvidence.value.filter(es => es.status === EvidenceStatus.ACTIVE)
  })

  /** Is there any stale evidence in the loaded set? */
  const hasStaleEvidence = computed(() => staleEvidence.value.length > 0)

  /** Highlight data for the overlay: array of { key, bboxes, polygons, status, color } */
  const highlights = computed(() => {
    const results = []
    const visited = new Set()

    // Build from evidence spans
    for (const es of currentPageEvidence.value) {
      const meta = es.metadata || {}
      const bboxes = Array.isArray(meta.bboxes) ? meta.bboxes : []
      const polygons = Array.isArray(meta.polygons) ? meta.polygons : []

      if (bboxes.length === 0 && polygons.length === 0) continue

      const key = es.blockId
      if (visited.has(key)) continue
      visited.add(key)

      results.push({
        key,
        evidenceSpan: es,
        bboxes,
        polygons,
        status: es.status,
        isActive: es.status === EvidenceStatus.ACTIVE,
        isStale: es.status === EvidenceStatus.STALE,
        isSuspended: es.status === EvidenceStatus.SUSPENDED,
        color: getHighlightColor(es.status, key === activeCitationKey.value, key === hoveredCitationKey.value),
        textSnippet: es.textSnippet,
      })
    }

    // Also include highlights from citations that reference evidence not in the current span list
    // (citations may carry pageOrSlide metadata for page-level filtering)
    for (const cit of citations.value) {
      if (cit.pageOrSlide != null && cit.pageOrSlide !== currentPage.value) continue
      if (!cit.key || visited.has(cit.key)) continue

      // Citation without evidence span detail — show page-level indicator
      visited.add(cit.key)
      results.push({
        key: cit.key,
        evidenceSpan: null,
        bboxes: [],
        polygons: [],
        status: 'active',
        isActive: true,
        isStale: false,
        isSuspended: false,
        color: getHighlightColor('active', cit.key === activeCitationKey.value, cit.key === hoveredCitationKey.value),
        textSnippet: null,
        pageOnly: true,
      })
    }

    return results
  })

  // ---- Methods ----

  function setTotalPages(n) {
    totalPages.value = Math.max(0, n)
  }

  function goToPage(n) {
    if (n < 1 || n > totalPages.value) return
    currentPage.value = n
    activeCitationKey.value = null
  }

  function nextPage() {
    goToPage(currentPage.value + 1)
  }

  function prevPage() {
    goToPage(currentPage.value - 1)
  }

  function setZoom(z) {
    zoom.value = Math.max(0.1, Math.min(5.0, z))
  }

  function zoomIn() {
    setZoom(zoom.value * 1.25)
  }

  function zoomOut() {
    setZoom(zoom.value / 1.25)
  }

  function resetZoom() {
    zoom.value = 1.0
  }

  function setRotation(r) {
    // Only allow 0, 90, 180, 270
    const allowed = [0, 90, 180, 270]
    const clamped = allowed.includes(r) ? r : 0
    rotation.value = clamped
  }

  function rotateClockwise() {
    setRotation((rotation.value + 90) % 360)
  }

  function rotateCounterClockwise() {
    setRotation((rotation.value - 90 + 360) % 360)
  }

  function selectCitation(key) {
    activeCitationKey.value = activeCitationKey.value === key ? null : key
  }

  function hoverCitation(key) {
    hoveredCitationKey.value = key
  }

  function unhoverCitation() {
    hoveredCitationKey.value = null
  }

  function setCitations(items) {
    citations.value = Array.isArray(items) ? items : []
  }

  function setEvidenceSpans(items) {
    evidenceSpans.value = Array.isArray(items) ? items : []
  }

  function setPageImageUrls(urls) {
    pageImageUrls.value = Array.isArray(urls) ? urls : []
  }

  function setLoading(val) {
    loading.value = !!val
  }

  function setError(err) {
    error.value = err ? String(err) : null
  }

  return {
    // State
    currentPage,
    totalPages,
    zoom,
    rotation,
    activeCitationKey,
    hoveredCitationKey,
    citations,
    evidenceSpans,
    pageImageUrls,
    loading,
    error,

    // Computed
    currentPageImageUrl,
    currentPageEvidence,
    staleEvidence,
    currentPageActiveEvidence,
    hasStaleEvidence,
    highlights,

    // Methods
    setTotalPages,
    goToPage,
    nextPage,
    prevPage,
    setZoom,
    zoomIn,
    zoomOut,
    resetZoom,
    setRotation,
    rotateClockwise,
    rotateCounterClockwise,
    selectCitation,
    hoverCitation,
    unhoverCitation,
    setCitations,
    setEvidenceSpans,
    setPageImageUrls,
    setLoading,
    setError,
  }
}

/**
 * Get highlight overlay color based on evidence status and interaction state.
 *
 * @param {string} status - Evidence status
 * @param {boolean} isActive - Is this the currently selected citation?
 * @param {boolean} isHovered - Is this citation being hovered?
 * @returns {string} CSS color string
 */
function getHighlightColor(status, isActive, isHovered) {
  if (isActive) return 'rgba(59, 130, 246, 0.4)'    // Blue for selected
  if (isHovered) return 'rgba(59, 130, 246, 0.25)'  // Light blue for hover
  if (status === EvidenceStatus.STALE) return 'rgba(234, 179, 8, 0.35)'     // Yellow for stale
  if (status === EvidenceStatus.SUSPENDED) return 'rgba(156, 163, 175, 0.3)' // Gray for suspended
  return 'rgba(34, 197, 94, 0.25)'                   // Green for active
}
