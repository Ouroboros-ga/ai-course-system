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
      :initialPage="initialPage"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import EvidenceViewerWithPanel from '@/features/evidence-viewer/components/EvidenceViewerWithPanel.vue'
import { fetchCanonicalEvidenceViewer, fetchProtectedImageUrl } from '@/api/evidence.js'

const route = useRoute()
const courseId = String(route.params.courseId || route.query.courseId || '')
const runId = String(route.params.runId || route.query.runId || '')
const initialPage = Math.max(1, Number(route.query.page || 1))
const documentId = ref('')
const loading = ref(true)
const error = ref(null)
const citations = ref([])
const evidenceSpans = ref([])
const pageImageUrls = ref([])
const objectUrls = []

onMounted(async () => {
  if (!courseId || !runId) {
    loading.value = false
    return
  }
  try {
    const data = await fetchCanonicalEvidenceViewer(courseId, runId)
    documentId.value = data.documentId
    citations.value = data.citations || []
    evidenceSpans.value = data.evidenceSpans
    pageImageUrls.value = await Promise.all((data.pageImageUrls || []).map(async (url) => {
      if (!url) return null
      try {
        const objectUrl = await fetchProtectedImageUrl(url)
        if (objectUrl) objectUrls.push(objectUrl)
        return objectUrl
      } catch {
        return null
      }
    }))
  } catch (reason) {
    error.value = reason?.message || String(reason)
  }
  loading.value = false
})

onUnmounted(() => {
  objectUrls.forEach((url) => URL.revokeObjectURL(url))
})
</script>

<style scoped>
.evidence-viewer-page { min-height: 60vh; padding: 24px; }
.ev-state { padding: 32px; text-align: center; color: #555; }
.ev-error { color: #c0392b; }
code { background: #f4f4f4; padding: 2px 6px; border-radius: 4px; }
</style>
