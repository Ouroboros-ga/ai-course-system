import request from '@/utils/request.js'

/**
 * 分屏视频播放器API
 * 提供播放器数据获取、进度保存等功能
 */

/**
 * 获取播放器初始化数据
 * @param {number} courseId 课程ID
 * @returns {Promise<Object>} 播放器初始化数据（课程信息、节点列表、视频URL等）
 */
export async function getPlayerInitData(courseId) {
  return request.get(`/player/init/${courseId}`)
}

/**
 * 获取知识点导航条数据
 * @param {number} courseId 课程ID
 * @returns {Promise<Object>} 知识点列表及完成状态
 */
export async function getKnowledgePoints(courseId) {
  return request.get(`/player/knowledge-points/${courseId}`)
}

/**
 * 保存学习进度
 * @param {Object} progressData 进度数据
 * @param {number} progressData.courseId 课程ID
 * @param {number} progressData.currentNodeId 当前节点ID
 * @param {number} progressData.currentTimestamp 当前播放时间(秒)
 * @param {number} progressData.currentPage 当前PPT页码
 * @param {Array<number>} progressData.completedNodes 已完成节点ID列表
 * @returns {Promise<Object>} 保存结果
 */
export async function savePlayerProgress(progressData) {
  return request.post('/player/progress/save', progressData)
}

/**
 * 获取学习进度（用于断点续播）
 * @param {number} courseId 课程ID
 * @returns {Promise<Object>} 学习进度数据
 */
export async function getPlayerProgress(courseId) {
  return request.get(`/player/progress/${courseId}`)
}
