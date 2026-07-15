<template>
  <div class="evidence-viewer-page">
    <div v-if="loading" class="ev-state ev-loading">加载证据数据…</div>
    <div v-else-if="error" class="ev-state ev-error">
      证据查看器不可用：{{ error }}
      <p class="ev-hint">
        V2 Evidence shadow 未启用或数据不可用（G4 阶段返回空/abstain，真实数据见 G5/G6）。
      </p>
    </div>
    <div v-else-if="!documentId" class="ev-state ev-empty">
      请通过 <code>/evidence-viewer/:documentId</code> 指定文档。
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
/**
 * P1-09 G4B: formal mount of the P1-04 Evidence Viewer.
 *
 * Thin wrapper view: reads documentId from the route, fetches citations /
 * evidence spans / page images from the V2 Evidence API
 * (internal-evidence-api/1.0, `/api/v1/evidence-v2`), and passes the
 * parsed data to EvidenceViewerWithPanel. RISK-02 coordinate highlight
 * fail-closed is enforced inside the P1-04 contracts.js parsers (invalid
 * data -> null, never displayed).
 *
 * G4: the endpoint returns empty/abstain (real data = G5/G6) and 503
 * SHADOW_FEATURE_DISABLED when EVIDENCE_CITATION_MODE is off. Each fetch
 * is settled independently so a 503 on one resource does not abort the
 * others; if all fail the page shows an unavailable state (fail-closed,
 * never a broken viewer).
 */
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import EvidenceViewerWithPanel from '@/features/evidence-viewer/components/EvidenceViewerWithPanel.vue'
import { fetchCitations, fetchEvidenceSpans, fetchDocumentPages } from '@/api/evidence.js'

const route = useRoute()
const documentId = String(route.params.documentId || route.query.documentId || '')

const loading = ref(true)
const error = ref(null)
const citations = ref([])
const evidenceSpans = ref([])
const pageImageUrls = ref([])

onMounted(async () => {
  if (!documentId) {
    loading.value = false
    return
  }
  const results = await Promise.allSettled([
    fetchCitations(documentId),
    fetchEvidenceSpans(documentId),
    fetchDocumentPages(documentId),
  ])
  const allRejected = results.every((r) => r.status === 'rejected')
  if (allRejected) {
    // All three failed (typically 503 SHADOW_FEATURE_DISABLED when flag off).
    const reason = results[0].reason
    error.value = (reason && (reason.message || String(reason))) || 'V2 Evidence shadow 未启用 (503)'
  } else {
    citations.value = results[0].status === 'fulfilled' ? results[0].value : []
    evidenceSpans.value = results[1].status === 'fulfilled' ? results[1].value : []
    pageImageUrls.value = results[2].status === 'fulfilled' ? results[2].value : []
  }
  loading.value = false
})
</script>

<style scoped>
.evidence-viewer-page {
  min-height: 60vh;
  padding: 24px;
}
.ev-state {
  padding: 32px;
  text-align: center;
  color: #555;
}
.ev-error {
  color: #c0392b;
}
.ev-hint {
  margin-top: 8px;
  font-size: 0.9em;
  color: #888;
}
code {
  background: #f4f4f4;
  padding: 2px 6px;
  border-radius: 4px;
}
</style>
