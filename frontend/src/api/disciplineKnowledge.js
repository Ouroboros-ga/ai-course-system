import request from '@/utils/request.js'

/**
 * XH-202620 CS 学科垂类知识库（只读检索）API 客户端。
 * 对应后端路由 backend/app/api/v1/endpoints/discipline_knowledge.py：
 *   GET  /api/v1/discipline-knowledge/search
 *   GET  /api/v1/discipline-knowledge/nodes/{node_id}
 *   GET  /api/v1/discipline-knowledge/overview
 *   POST /api/v1/discipline-knowledge/reload
 */
export function searchDisciplineKnowledge(q, topK = 5) {
  return request.get('/discipline-knowledge/search', { params: { q, top_k: topK } })
}

export function getDisciplineKnowledgeNode(nodeId) {
  return request.get(`/discipline-knowledge/nodes/${encodeURIComponent(nodeId)}`)
}

export function getDisciplineKnowledgeOverview() {
  return request.get('/discipline-knowledge/overview')
}

export function reloadDisciplineKnowledge() {
  return request.post('/discipline-knowledge/reload')
}
