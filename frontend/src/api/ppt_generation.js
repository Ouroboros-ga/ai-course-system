import request from '@/utils/request.js'

/**
 * F3 · AI生成PPT课件 API
 */

// 获取PPT模板列表
export function getPPTThemes(params = {}) {
  return request.get('/ppt-generation/themes', { params })
}

// AI生成PPT（异步，返回任务ID）
export function generatePPT(data) {
  return request.post('/ppt-generation/generate', data)
}

// AI生成PPT（同步，等待完成）
export function generatePPTSync(data) {
  return request.post('/ppt-generation/generate-sync', data)
}

// 查询PPT生成任务进度
export function getPPTTaskStatus(sid) {
  return request.get(`/ppt-generation/task/${sid}`)
}
