import request from '@/utils/request.js'

/**
 * 知识点↔PPT页面映射管理API
 */

// 获取课程映射详情（含知识点列表、PPT页面文本、映射关系）
export function getMappingDetail(courseId) {
  return request.get(`/mapping/${courseId}`)
}

// 获取PPT逐页文本
export function getPageTexts(courseId) {
  return request.get(`/mapping/${courseId}/pages`)
}

// 自动生成映射（基于ScriptNode已有的page_start/page_end）
export function autoGenerateMapping(courseId) {
  return request.post(`/mapping/${courseId}/auto`)
}

// AI语义匹配映射
export function aiMatchMapping(courseId) {
  return request.post(`/mapping/${courseId}/ai-match`)
}

// 手动调整单个知识点映射
export function updateNodeMapping(courseId, nodeId, pageStart, pageEnd) {
  return request.put(`/mapping/${courseId}/nodes/${nodeId}`, {
    node_id: nodeId,
    page_start: pageStart,
    page_end: pageEnd,
  })
}

// 批量更新映射关系
export function batchUpdateMapping(courseId, updates) {
  return request.put(`/mapping/${courseId}/batch`, { updates })
}

// 应用映射到脚本（视频生成前必须调用）
export function applyMapping(courseId) {
  return request.post(`/mapping/${courseId}/apply`)
}
