/**
 * useGraphBrowser — assemble the graph from REAL endpoints only.
 *
 * Layers (each optional, never fabricated):
 *   - course + knowledge-point structure  <- GET /api/v1/mapping/{courseId}
 *   - evidence spans / citations          <- /api/v1/evidence-v2 (V2, flag-gated)
 *
 * RetrievalTrace is intentionally NOT fabricated: there is no real
 * `/graph/replay` / trace endpoint yet, so `trace` stays null and the panel
 * renders an explicit empty state (report discipline).
 */
import { computed, ref } from 'vue'
import { getMappingDetail } from '@/api/mapping.js'
import { getCourseWorkspaceContext } from '@/api/course_workspace.js'
import { fetchCitations, fetchEvidenceSpans } from '@/api/evidence.js'
import {
  GRAPH_BROWSER_SCHEMA_VERSION,
  assertGraphBrowserSchema,
  parseGraphEdge,
  parseGraphNode,
} from '../contracts.js'

export function useGraphBrowser() {
  const loading = ref(false)
  const error = ref('')
  const evidenceError = ref('')
  const courseTitle = ref('')
  const documentId = ref(null)

  const rawNodes = ref([])
  const rawEdges = ref([])
  const evidenceNodes = ref([])
  const trace = ref(null) // no real trace endpoint yet — stays null (not fabricated)

  const nodes = computed(() => rawNodes.value)
  const edges = computed(() => rawEdges.value)

  async function load(courseId) {
    loading.value = true
    error.value = ''
    evidenceError.value = ''
    rawNodes.value = []
    rawEdges.value = []
    evidenceNodes.value = []

    // The graph is course-scoped.  Do not issue a malformed request such as
    // `/document/course/undefined` when the optional route parameter is absent.
    const normalizedCourseId = String(courseId ?? '').trim()
    if (!/^\d+$/.test(normalizedCourseId) || Number(normalizedCourseId) <= 0) {
      error.value = '请选择课程后再查看图谱：从“知识点映射”进入，或访问 /graph-browser/<课程ID>。'
      loading.value = false
      return
    }

    // validate our own frozen schema (fail-closed on unknown major)
    try {
      assertGraphBrowserSchema(GRAPH_BROWSER_SCHEMA_VERSION)
    } catch (e) {
      error.value = String(e.message || e)
      loading.value = false
      return
    }

    try {
      const [mapping, context] = await Promise.all([
        getMappingDetail(normalizedCourseId),
        getCourseWorkspaceContext(normalizedCourseId).catch(() => null),
      ])

      const nodeList = mapping?.nodes || []
      courseTitle.value = context?.course?.title || `课程 #${courseId}`
      documentId.value = context?.course?.document_id || context?.document?.document_id || null

      const courseNodeId = `course:${normalizedCourseId}`
      const nextNodes = []
      const nextEdges = []

      nextNodes.push(parseGraphNode({
        id: courseNodeId,
        kind: 'course',
        label: courseTitle.value,
      }))

      for (const n of nodeList) {
        const kpId = `kp:${n.node_id}`
        nextNodes.push(parseGraphNode({
          id: kpId,
          kind: 'knowledge_point',
          label: n.title || `知识点 ${n.node_id}`,
          pageStart: n.page_start ?? null,
          pageEnd: n.page_end ?? null,
          confidence: n.confidence ?? null,
          isManual: n.is_manual === true,
        }))
        nextEdges.push(parseGraphEdge({ source: courseNodeId, target: kpId, kind: 'contains' }))
      }

      // evidence layer (real, flag-gated). Failure => explicit evidenceError, not fabricated.
      if (documentId.value) {
        try {
          const [spans, citations] = await Promise.all([
            fetchEvidenceSpans(documentId.value),
            fetchCitations(documentId.value),
          ])
          const citeCountBySpan = new Map()
          for (const c of citations) {
            const ref = c.evidenceRef
            if (!ref) continue
            citeCountBySpan.set(ref, (citeCountBySpan.get(ref) || 0) + 1)
          }
          const evNodes = []
          for (const s of spans) {
            const spanId = s.blockId || s.artifactId
            const evId = `ev:${spanId}`
            const page = s.pageOrSlide ?? null
            const evNode = parseGraphNode({
              id: evId,
              kind: 'evidence',
              label: s.textSnippet ? s.textSnippet.slice(0, 18) : `证据 ${spanId}`,
              documentId: s.documentId || documentId.value,
              spanId,
              pageStart: page,
              citationCount: citeCountBySpan.get(spanId) || 0,
            })
            if (!evNode) continue
            evNodes.push(evNode)
            // attach evidence to the knowledge point whose page range covers it
            const owner = nodeList.find((n) =>
              page != null && Number.isFinite(n.page_start) && Number.isFinite(n.page_end) &&
              page >= n.page_start && page <= n.page_end
            )
            const target = owner ? `kp:${owner.node_id}` : courseNodeId
            nextEdges.push(parseGraphEdge({ source: target, target: evId, kind: 'has_evidence' }))
          }
          evidenceNodes.value = evNodes
          nextNodes.push(...evNodes)
        } catch {
          evidenceError.value = '证据拉取失败（V2 影子可能未放量，或当前账号无权限）。图谱其余部分不受影响。'
        }
      }

      rawNodes.value = nextNodes.filter(Boolean)
      rawEdges.value = nextEdges.filter(Boolean)
    } catch {
      error.value = '图谱数据暂时无法读取。请确认课程已解析且当前账号有访问权限。'
    } finally {
      loading.value = false
    }
  }

  return {
    loading, error, evidenceError,
    courseTitle, documentId,
    nodes, edges, evidenceNodes, trace,
    load,
  }
}
