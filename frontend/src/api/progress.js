import request from '@/utils/request.js'

/**
 * 分析学生理解度
 * @param {Object} data - 请求参数
 * @param {number} data.courseId - 课程ID
 * @param {number} data.nodeId - 当前节点ID
 * @param {string} data.question - 学生提问内容
 * @param {number} [data.chatId] - 会话ID
 */
export function analyzeUnderstanding(data) {
  return request({
    url: '/progress/analyze',
    method: 'post',
    data: {
      courseId: data.courseId,
      nodeId: data.nodeId,
      question: data.question,
      chatId: data.chatId || null
    }
  })
}

/**
 * 获取学习进度可视化数据
 * @param {number} courseId - 课程ID
 */
export function getVisualization(courseId) {
  return request({
    url: `/progress/visualization/${courseId}`,
    method: 'get'
  })
}

/**
 * 同步学习进度
 * @param {Object} data - 请求参数
 * @param {number} data.courseId - 课程ID
 * @param {number} data.nodeId - 当前节点ID
 * @param {number} data.timestamp - 当前播放时间点(秒)
 * @param {boolean} [data.isCompleted] - 当前节点是否已完成
 * @param {number} [data.timeSpent] - 本次学习时长(秒)
 */
export function syncProgress(data) {
  return request({
    url: '/progress/sync',
    method: 'post',
    data: {
      courseId: data.courseId,
      nodeId: data.nodeId,
      timestamp: data.timestamp,
      isCompleted: data.isCompleted || false,
      timeSpent: data.timeSpent || 0
    }
  })
}

/**
 * 获取断点续接信息
 * @param {number} courseId - 课程ID
 */
export function getResumePoint(courseId) {
  return request({
    url: `/progress/resume/${courseId}`,
    method: 'get'
  })
}

/**
 * 标记节点为已完成
 * @param {Object} data - 请求参数
 * @param {number} data.courseId - 课程ID
 * @param {number} data.nodeId - 节点ID
 */
export function markNodeCompleted(data) {
  return request({
    url: '/progress/node/complete',
    method: 'post',
    data: {
      courseId: data.courseId,
      nodeId: data.nodeId
    }
  })
}

export default {
  analyzeUnderstanding,
  getVisualization,
  syncProgress,
  getResumePoint,
  markNodeCompleted
}
