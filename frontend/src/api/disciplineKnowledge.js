import request from '@/utils/request.js'

/**
 * XH-202620 CS 学科垂类知识库（只读检索）API 客户端。
 * 对应后端路由 backend/app/api/v1/endpoints/discipline_knowledge.py：
 *   GET  /api/v1/discipline-knowledge/search?mode=concept|corpus|all
 *   GET  /api/v1/discipline-knowledge/nodes/{node_id}
 *   GET  /api/v1/discipline-knowledge/overview
 *   GET  /api/v1/discipline-knowledge/chunks/{chunk_id}?release_id=...
 *   POST /api/v1/discipline-knowledge/reload
 *
 * 资料模式只调用 chunk 引用端点取原文（固定 release_id）；不拼磁盘路径。
 */
export function searchDisciplineKnowledge(q, topK = 5, mode = 'concept') {
  return request.get('/discipline-knowledge/search', { params: { q, top_k: topK, mode } })
}

export function getDisciplineKnowledgeNode(nodeId) {
  return request.get(`/discipline-knowledge/nodes/${encodeURIComponent(nodeId)}`)
}

export function getDisciplineCorpusChunk(chunkId, releaseId) {
  return request.get(`/discipline-knowledge/chunks/${encodeURIComponent(chunkId)}`, {
    params: { release_id: releaseId },
  })
}

export function getDisciplineKnowledgeOverview() {
  return request.get('/discipline-knowledge/overview')
}

export function reloadDisciplineKnowledge() {
  return request.post('/discipline-knowledge/reload')
}
