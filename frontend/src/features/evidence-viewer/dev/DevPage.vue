<template>
  <div class="ev-dev-page">
    <header class="ev-dev-header">
      <h1>P1-04 Evidence Viewer — Dev Page</h1>
      <p class="ev-dev-subtitle">
        Isolated fixture-based development page for the evidence viewer feature.
        This page demonstrates the viewer with sample citation and evidence data.
      </p>
    </header>

    <!-- Scenario selector -->
    <section class="ev-dev-controls">
      <h2>Test Scenarios</h2>
      <div class="ev-dev-scenarios">
        <button
          v-for="sc in scenarios"
          :key="sc.id"
          class="ev-dev-btn"
          :class="{ 'ev-dev-btn--active': activeScenario === sc.id }"
          @click="loadScenario(sc.id)"
        >
          {{ sc.label }}
        </button>
      </div>
    </section>

    <!-- Viewer -->
    <section class="ev-dev-viewer-wrapper">
      <EvidenceViewerWithPanel
        :documentId="viewerData.documentId"
        :artifactId="viewerData.artifactId"
        :citations="viewerData.citations"
        :evidenceSpans="viewerData.evidenceSpans"
        :pageImageUrls="viewerData.pageImageUrls"
        :totalPages="viewerData.totalPages"
        :initialPage="1"
        :initialZoom="1.0"
        :initialRotation="0"
        :error="viewerData.error"
      />
    </section>

    <!-- Debug info -->
    <section class="ev-dev-debug">
      <details>
        <summary>Debug Info</summary>
        <div class="ev-dev-debug-content">
          <h3>Active Scenario: {{ activeScenario }}</h3>
          <h4>Citations ({{ viewerData.citations.length }})</h4>
          <pre>{{ JSON.stringify(viewerData.citations, null, 2) }}</pre>
          <h4>Evidence Spans ({{ viewerData.evidenceSpans.length }})</h4>
          <pre>{{ JSON.stringify(viewerData.evidenceSpans, null, 2) }}</pre>
        </div>
      </details>
    </section>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import EvidenceViewerWithPanel from '../components/EvidenceViewerWithPanel.vue'
import {
  createSampleViewerState,
  SAMPLE_CITATIONS,
  SAMPLE_EVIDENCE_SPANS,
  STALE_VERSION_EVIDENCE,
  INVALID_COORDINATE_EVIDENCE,
} from '../fixtures/sampleData.js'
import { createSamplePageUrls } from '../fixtures/sampleData.js'

// ---- Scenarios ----

const scenarios = [
  { id: 'normal', label: 'Normal Active Evidence' },
  { id: 'multi-region', label: 'Multi-Region Highlights' },
  { id: 'stale', label: 'Stale Evidence Warning' },
  { id: 'missing-coords', label: 'Missing Coordinates' },
  { id: 'invalid-coords', label: 'Invalid Coordinates (fail-closed)' },
  { id: 'error', label: 'Error State' },
  { id: 'empty', label: 'Empty State' },
]

const activeScenario = ref('normal')

const viewerData = reactive({
  documentId: '',
  artifactId: '',
  citations: [],
  evidenceSpans: [],
  pageImageUrls: [],
  totalPages: 0,
  error: null,
})

// ---- Scenario loaders ----

function loadScenario(id) {
  activeScenario.value = id

  // Reset
  viewerData.error = null

  const base = createSampleViewerState()

  switch (id) {
    case 'normal': {
      // Normal: all active evidence, one page
      viewerData.documentId = base.documentId
      viewerData.artifactId = base.artifactId
      viewerData.totalPages = 1
      viewerData.pageImageUrls = createSamplePageUrls(1)
      viewerData.citations = [SAMPLE_CITATIONS[0]] // single citation on page 1
      viewerData.evidenceSpans = [SAMPLE_EVIDENCE_SPANS[0]] // active, page 1
      break
    }

    case 'multi-region': {
      // Multiple bboxes per evidence (BST properties spanning multiple regions)
      viewerData.documentId = base.documentId
      viewerData.artifactId = base.artifactId
      viewerData.totalPages = 1
      viewerData.pageImageUrls = createSamplePageUrls(1)
      viewerData.citations = [SAMPLE_CITATIONS[3]] // BST citation with 3 regions
      viewerData.evidenceSpans = [SAMPLE_EVIDENCE_SPANS[2]] // 3 bboxes
      break
    }

    case 'stale': {
      // Stale evidence on page 5
      viewerData.documentId = base.documentId
      viewerData.artifactId = base.artifactId
      viewerData.totalPages = 1
      viewerData.pageImageUrls = createSamplePageUrls(1)
      viewerData.citations = [SAMPLE_CITATIONS[4]] // stale citation
      viewerData.evidenceSpans = [STALE_VERSION_EVIDENCE]
      break
    }

    case 'missing-coords': {
      // Evidence without coordinate data
      viewerData.documentId = base.documentId
      viewerData.artifactId = base.artifactId
      viewerData.totalPages = 1
      viewerData.pageImageUrls = createSamplePageUrls(1)
      viewerData.citations = [SAMPLE_CITATIONS[5]] // no-coord citation
      viewerData.evidenceSpans = [SAMPLE_EVIDENCE_SPANS[6]] // no bboxes
      break
    }

    case 'invalid-coords': {
      // Invalid coordinate data (out of bounds)
      viewerData.documentId = base.documentId
      viewerData.artifactId = base.artifactId
      viewerData.totalPages = 1
      viewerData.pageImageUrls = createSamplePageUrls(1)
      viewerData.citations = [] // no valid citations for invalid coords
      viewerData.evidenceSpans = [INVALID_COORDINATE_EVIDENCE]
      break
    }

    case 'error': {
      // Fatal error state
      viewerData.documentId = base.documentId
      viewerData.artifactId = base.artifactId
      viewerData.totalPages = 0
      viewerData.pageImageUrls = []
      viewerData.citations = []
      viewerData.evidenceSpans = []
      viewerData.error = 'Failed to load document data. The evidence viewer cannot render without valid input.'
      break
    }

    case 'empty': {
      // Empty state (no data)
      viewerData.documentId = ''
      viewerData.artifactId = ''
      viewerData.totalPages = 0
      viewerData.pageImageUrls = []
      viewerData.citations = []
      viewerData.evidenceSpans = []
      break
    }

    default: {
      // Full sample (all pages, all data)
      Object.assign(viewerData, base)
    }
  }
}

// Load default scenario
loadScenario('normal')
</script>

<style scoped>
.ev-dev-page {
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.ev-dev-header {
  margin-bottom: 20px;
}

.ev-dev-header h1 {
  margin: 0;
  font-size: 22px;
  color: #1f2937;
}

.ev-dev-subtitle {
  margin: 6px 0 0;
  color: #6b7280;
  font-size: 13px;
}

.ev-dev-controls {
  margin-bottom: 16px;
}

.ev-dev-controls h2 {
  margin: 0 0 8px;
  font-size: 14px;
  color: #374151;
}

.ev-dev-scenarios {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.ev-dev-btn {
  padding: 6px 14px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: #fff;
  font-size: 12px;
  color: #374151;
  cursor: pointer;
  transition: all 0.1s ease;
}

.ev-dev-btn:hover {
  border-color: #93c5fd;
  background: #eff6ff;
}

.ev-dev-btn--active {
  border-color: #3b82f6;
  background: #3b82f6;
  color: #fff;
}

.ev-dev-viewer-wrapper {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
  min-height: 500px;
  height: 70vh;
}

.ev-dev-debug {
  margin-top: 16px;
}

.ev-dev-debug summary {
  cursor: pointer;
  font-size: 13px;
  color: #6b7280;
  padding: 4px 0;
}

.ev-dev-debug-content {
  font-size: 12px;
  max-height: 400px;
  overflow-y: auto;
  background: #f9fafb;
  padding: 12px;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
}

.ev-dev-debug-content pre {
  white-space: pre-wrap;
  font-size: 11px;
  background: #f3f4f6;
  padding: 8px;
  border-radius: 4px;
}
</style>
