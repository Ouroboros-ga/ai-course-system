const NODE_KIND = Object.freeze({
  Course: 'course',
  Chapter: 'chapter',
  KnowledgePoint: 'knowledge_point',
  PPTSlide: 'ppt_slide',
  ScriptNode: 'script_node',
  Evidence: 'evidence',
})

const EDGE_KIND = Object.freeze({
  CONTAINS: 'contains',
  GROUNDED_BY: 'grounded_by',
  MAPPED_TO: 'mapped_to',
  NEXT: 'next',
})

export function citationToPptLocator(hit, citation) {
  const page = Number(citation?.page_or_slide ?? hit?.page_or_slide)
  if (!Number.isInteger(page) || page < 1 || !hit?.course_id || !citation?.citation_key) return null
  return {
    courseId: String(hit.course_id),
    pageOrSlide: page,
    blockId: citation.block_id || hit.block_id || null,
    citationKey: citation.citation_key,
    evidenceId: citation.research_evidence_id || null,
  }
}

export function snapshotToCanvasGraph(snapshot) {
  const nodes = Array.isArray(snapshot?.nodes) ? snapshot.nodes : []
  const edges = Array.isArray(snapshot?.edges) ? snapshot.edges : []
  const validNodes = nodes
    .filter((node) => node && typeof node.node_id === 'string' && NODE_KIND[node.node_type])
    .map((node) => {
      const properties = node.properties || {}
      const label = properties.canonical_label || properties.title || (
        node.node_type === 'PPTSlide' ? `PPT 第 ${properties.slide_number || '?'} 页` : node.source_id
      )
      return {
        id: node.node_id,
        kind: NODE_KIND[node.node_type],
        label: String(label || node.node_type),
        nodeType: node.node_type,
        sourceId: node.source_id,
        courseId: node.course_id,
        properties,
      }
    })
  const ids = new Set(validNodes.map((node) => node.id))
  const validEdges = edges
    .filter((edge) => edge?.status === 'accepted' && EDGE_KIND[edge.predicate] && ids.has(edge.subject_node_id) && ids.has(edge.object_node_id))
    .map((edge) => ({
      source: edge.subject_node_id,
      target: edge.object_node_id,
      kind: EDGE_KIND[edge.predicate],
      predicate: edge.predicate,
      evidenceIds: edge.research_evidence_ids || [],
    }))
  return { nodes: validNodes, edges: validEdges }
}
