<template>
  <div class="evidence-viewer-page">
    <div v-if="loading" class="ev-state ev-loading">Loading evidence data...</div>
    <div v-else-if="error" class="ev-state ev-error">
      Evidence viewer is unavailable: {{ error }}
    </div>
    <div v-else-if="!documentId" class="ev-state ev-empty">
      Specify a parse run with <code>/evidence-viewer/:courseId/:runId</code>.
    </div>
    <EvidenceViewerWithPanel
      v-else
      :documentId="documentId"
      :citations="citations"
      :evidenceSpans="evidenceSpans"
      :pageImageUrls="pageImageUrls"
      :totalPages="pageImageUrls.length"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import EvidenceViewerWithPanel from '@/features/evidence-viewer/components/EvidenceViewerWithPanel.vue'
import { fetchCanonicalEvidenceViewer } from '@/api/evidence.js'

const route = useRoute()
const courseId = String(route.params.courseId || route.query.courseId || '')
const runId = String(route.params.runId || route.query.runId || '')
const documentId = ref('')
const loading = ref(true)
const error = ref(null)
const citations = ref([])
const evidenceSpans = ref([])
const pageImageUrls = ref([])

onMounted(async () => {
  if (!courseId || !runId) {
    loading.value = false
    return
  }
  try {
    const data = await fetchCanonicalEvidenceViewer(courseId, runId)
    documentId.value = data.documentId
    evidenceSpans.value = data.evidenceSpans
    pageImageUrls.value = data.pageImageUrls
  } catch (reason) {
    error.value = reason?.message || String(reason)
  }
  loading.value = false
})
</script>

<style scoped>
.evidence-viewer-page { min-height: 60vh; padding: 24px; }
.ev-state { padding: 32px; text-align: center; color: #555; }
.ev-error { color: #c0392b; }
code { background: #f4f4f4; padding: 2px 6px; border-radius: 4px; }
</style>
