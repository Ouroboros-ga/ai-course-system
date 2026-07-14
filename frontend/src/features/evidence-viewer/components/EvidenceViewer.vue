<template>
  <div class="ev-evidence-viewer" :class="{ 'ev--loading': loading }">
    <!-- Error state (fail-closed on invalid data) -->
    <div v-if="fatalError" class="ev-fatal-error" role="alert">
      <h3>Viewer Error</h3>
      <p>{{ fatalError }}</p>
    </div>

    <!-- Viewer layout -->
    <template v-else>
      <!-- Document info bar -->
      <div class="ev-doc-bar" v-if="documentId">
        <span class="ev-doc-id">Document: <code>{{ documentId }}</code></span>
        <span class="ev-doc-artifact" v-if="artifactId">
          Artifact: <code>{{ artifactId }}</code>
        </span>
      </div>

      <div class="ev-viewer-layout">
        <!-- Page viewer -->
        <PageViewer
          :currentPage="currentPage"
          :totalPages="totalPages"
          :zoom="zoom"
          :rotation="rotation"
          :pageImageUrl="currentPageImageUrl"
          :highlights="highlights"
          :activeCitationKey="activeCitationKey"
          :status="viewerStatus"
          :showOverlay="!fatalError"
          @prev-page="prevPage"
          @next-page="nextPage"
          @go-to-page="goToPage"
          @zoom-in="zoomIn"
          @zoom-out="zoomOut"
          @zoom-reset="resetZoom"
          @rotate-cw="rotateClockwise"
        />
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, watch, ref } from 'vue'
import { useViewer } from '../composables/useViewer.js'
import PageViewer from './PageViewer.vue'

const props = defineProps({
  /** Stable document ID */
  documentId: { type: String, default: '' },
  /** Stable artifact ID */
  artifactId: { type: String, default: '' },
  /** Array of Citation objects */
  citations: { type: Array, default: () => [] },
  /** Array of EvidenceSpan objects */
  evidenceSpans: { type: Array, default: () => [] },
  /** Array of page image URLs (index 0 = page 1) */
  pageImageUrls: { type: Array, default: () => [] },
  /** Total number of pages */
  totalPages: { type: Number, default: 0 },
  /** Initial page (1-based) */
  initialPage: { type: Number, default: 1 },
  /** Initial zoom level */
  initialZoom: { type: Number, default: 1.0 },
  /** Initial rotation in degrees */
  initialRotation: { type: Number, default: 0 },
  /** Whether viewer is read-only */
  readOnly: { type: Boolean, default: false },
  /** Optional error message to display */
  error: { type: String, default: null },
})

const emit = defineEmits([
  'citation-select',
  'citation-hover',
  'citation-unhover',
  'page-change',
  'zoom-change',
  'rotation-change',
])

// ---- Initialize viewer state ----

const fatalError = ref(props.error || null)

const viewer = useViewer({
  totalPages: props.totalPages,
  initialPage: props.initialPage,
  initialZoom: props.initialZoom,
  initialRotation: props.initialRotation,
})

// ---- Sync props to state ----

watch(() => props.documentId, (val) => {
  if (val) fatalError.value = null
})

watch(() => props.citations, (val) => {
  viewer.setCitations(val)
}, { immediate: true })

watch(() => props.evidenceSpans, (val) => {
  viewer.setEvidenceSpans(val)
}, { immediate: true })

watch(() => props.pageImageUrls, (val) => {
  viewer.setPageImageUrls(val)
}, { immediate: true })

watch(() => props.totalPages, (val) => {
  viewer.setTotalPages(val)
}, { immediate: true })

watch(() => props.error, (val) => {
  fatalError.value = val || null
})

// ---- Computed from viewer state ----

const {
  currentPage,
  totalPages,
  zoom,
  rotation,
  activeCitationKey,
  hoveredCitationKey,
  currentPageImageUrl,
  highlights,
  hasStaleEvidence,
  staleEvidence,
} = viewer

/**
 * Determine the viewer overlay status based on evidence states.
 * RISK-02: Show explicit indicators for stale/missing/invalid states.
 */
const viewerStatus = computed(() => {
  if (fatalError.value) return 'invalid'
  if (hasStaleEvidence.value) return 'stale'

  // Check for evidence without coordinates (missing)
  const evidenceList = props.evidenceSpans || []
  const hasMissingCoords = evidenceList.some(es => {
    const meta = es.metadata || {}
    const bboxes = Array.isArray(meta.bboxes) ? meta.bboxes : []
    const polygons = Array.isArray(meta.polygons) ? meta.polygons : []
    return bboxes.length === 0 && polygons.length === 0 && es.status === 'active'
  })
  if (hasMissingCoords) return 'missing'

  return null
})

// ---- Expose viewer methods (for parent component use) ----

function goToPage(n) {
  viewer.goToPage(n)
  emit('page-change', n)
}

function prevPage() {
  viewer.prevPage()
  emit('page-change', viewer.currentPage.value)
}

function nextPage() {
  viewer.nextPage()
  emit('page-change', viewer.currentPage.value)
}

function zoomIn() { viewer.zoomIn(); emit('zoom-change', viewer.zoom.value) }
function zoomOut() { viewer.zoomOut(); emit('zoom-change', viewer.zoom.value) }
function resetZoom() { viewer.resetZoom(); emit('zoom-change', viewer.zoom.value) }
function rotateClockwise() { viewer.rotateClockwise(); emit('rotation-change', viewer.rotation.value) }

function selectCitation(key) {
  viewer.selectCitation(key)
  emit('citation-select', key)
}

function hoverCitation(key) {
  viewer.hoverCitation(key)
  emit('citation-hover', key)
}

function unhoverCitation() {
  viewer.unhoverCitation()
  emit('citation-unhover')
}

// Expose for template access
defineExpose({
  goToPage,
  prevPage,
  nextPage,
  zoomIn,
  zoomOut,
  resetZoom,
  rotateClockwise,
  selectCitation,
  currentPage,
  zoom,
  rotation,
  highlights,
})
</script>

<style scoped>
.ev-evidence-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 400px;
  background: #f0f1f3;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
}

.ev--loading {
  opacity: 0.7;
}

.ev-fatal-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
  color: #dc2626;
}

.ev-fatal-error h3 {
  margin: 0 0 8px;
  font-size: 16px;
}

.ev-fatal-error p {
  margin: 0;
  font-size: 13px;
  color: #6b7280;
}

.ev-doc-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 14px;
  background: #f8fafc;
  border-bottom: 1px solid #e5e7eb;
  font-size: 12px;
  color: #6b7280;
  flex-shrink: 0;
}

.ev-doc-id code,
.ev-doc-artifact code {
  font-size: 11px;
  color: #374151;
  background: #f1f5f9;
  padding: 1px 4px;
  border-radius: 3px;
}

.ev-viewer-layout {
  flex: 1;
  display: flex;
  overflow: hidden;
}
</style>
