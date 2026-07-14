<template>
  <div class="ev-viewer-with-panel">
    <!-- Main viewer -->
    <EvidenceViewer
      ref="viewerRef"
      :documentId="documentId"
      :artifactId="artifactId"
      :citations="citations"
      :evidenceSpans="evidenceSpans"
      :pageImageUrls="pageImageUrls"
      :totalPages="totalPages"
      :initialPage="initialPage"
      :initialZoom="initialZoom"
      :initialRotation="initialRotation"
      :error="error"
      @citation-select="onCitationSelect"
      @citation-hover="onCitationHover"
      @citation-unhover="onCitationUnhover"
      @page-change="onPageChange"
    />

    <!-- Citation panel -->
    <CitationPanel
      :citations="citations"
      :activeCitationKey="activeCitationKey"
      :currentPage="currentPage"
      :hasStaleEvidence="hasStaleEvidence"
      @select-citation="onCitationSelect"
      @hover-citation="onCitationHover"
      @unhover-citation="onCitationUnhover"
    />
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import EvidenceViewer from './EvidenceViewer.vue'
import CitationPanel from './CitationPanel.vue'

const props = defineProps({
  documentId: { type: String, default: '' },
  artifactId: { type: String, default: '' },
  citations: { type: Array, default: () => [] },
  evidenceSpans: { type: Array, default: () => [] },
  pageImageUrls: { type: Array, default: () => [] },
  totalPages: { type: Number, default: 0 },
  initialPage: { type: Number, default: 1 },
  initialZoom: { type: Number, default: 1.0 },
  initialRotation: { type: Number, default: 0 },
  error: { type: String, default: null },
})

const viewerRef = ref(null)
const activeCitationKey = ref(null)
const currentPage = ref(props.initialPage ?? 1)
const hasStaleEvidence = computed(() => {
  return (props.evidenceSpans || []).some(es => es.status === 'stale')
})

function onCitationSelect(key) {
  activeCitationKey.value = activeCitationKey.value === key ? null : key
  if (viewerRef.value) {
    viewerRef.value.selectCitation(key)
  }
}

function onCitationHover(key) {
  if (viewerRef.value) {
    viewerRef.value.hoverCitation?.(key)
  }
}

function onCitationUnhover() {
  if (viewerRef.value) {
    viewerRef.value.unhoverCitation?.()
  }
}

function onPageChange(page) {
  currentPage.value = page
  activeCitationKey.value = null
}
</script>

<style scoped>
.ev-viewer-with-panel {
  display: flex;
  height: 100%;
  width: 100%;
  overflow: hidden;
}

.ev-viewer-with-panel > .ev-evidence-viewer {
  flex: 1;
  min-width: 0;
}
</style>
