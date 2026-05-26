import request from '@/utils/request.js'

/**
 * F4 · 视频脚本编辑 API
 */

// 创建脚本版本快照
export function createScriptSnapshot(courseId, versionName) {
  return request.post(`/document/course/${courseId}/script/snapshot`, {
    version_name: versionName || undefined,
  })
}

// 获取脚本版本列表
export function getScriptVersions(courseId) {
  return request.get(`/document/course/${courseId}/script/versions`)
}

// 回滚到指定脚本版本
export function rollbackScriptVersion(courseId, scriptId) {
  return request.post(`/document/course/${courseId}/script/rollback/${scriptId}`)
}

// 保存课程节点（含extra_data）
export function saveCourseNodes(courseId, nodes) {
  return request.post(`/document/course/${courseId}/save`, { nodes })
}
