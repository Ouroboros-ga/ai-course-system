import request from '@/utils/request.js'
import { sanitizePlanListParams } from './visualizationRequestGuards.js'

/**
 * G4 算法可视化 API
 *
 * 全部对接真实 V1 端点，响应经 request.js 统一剥离 code/message。
 * 后端使用 course-access 权限解析器进行课程级权限校验：
 * - 列出算法: course.view
 * - 创建计划: course.mapping.edit (教师)
 * - 查看计划: course.content.read (学生+教师)
 * - 发布计划: course.mapping.edit (教师)
 */

/**
 * 列出所有允许的算法（白名单）。
 * GET /visualization/algorithms -> { algorithms: [...] }
 *
 * 每个算法包含: algorithm_id, name, category, description, params[], step_types[]
 */
export function listAlgorithms() {
  return request.get('/visualization/algorithms')
}

/**
 * 创建并验证可视化计划。
 * POST /visualization/course/{courseId}/plan
 *
 * 后端验证算法白名单、参数范围、步骤类型，拒绝任意 JS/HTML。
 * @param {number} courseId - 课程 ID
 * @param {object} data - 创建请求体 (CreatePlanRequest)
 * @param {string} data.algorithm_id - 算法标识(白名单内)
 * @param {object} data.initial_params - 初始参数
 * @param {Array} data.steps - 步骤列表
 * @param {Array} [data.highlights] - 高亮列表
 * @param {number} [data.playback_speed] - 回放速度
 * @param {object} [data.return_anchor] - 返回锚点
 * @param {number} [data.node_id] - 关联知识点节点 ID
 */
export function createPlan(courseId, data) {
  return request.post(`/visualization/course/${courseId}/plan`, data)
}

/**
 * 列出课程的可视化计划。
 * GET /visualization/course/{courseId}/plans
 *
 * 学生只能查看 published 状态的计划。
 * @param {number} courseId - 课程 ID
 * @param {object} [params] - 查询参数
 * @param {number} [params.node_id] - 按知识点筛选
 * @param {string} [params.status] - 按状态筛选
 */
export function listPlans(courseId, params = {}) {
  return request.get(`/visualization/course/${courseId}/plans`, {
    params: sanitizePlanListParams(params),
  })
}

/**
 * 获取可视化计划详情（用于回放）。
 * GET /visualization/{planId}
 *
 * 响应包含 plan_data（经过验证和净化的 VisualizationPlan JSON），
 * 且回放统计 play_count 递增。
 * @param {string} planId - 计划 UUID
 */
export function getPlan(planId) {
  return request.get(`/visualization/${planId}`)
}

/**
 * 发布可视化计划给学生使用。
 * POST /visualization/course/{courseId}/{planId}/publish
 *
 * 需要 course.mapping.edit 权限(教师)。
 * @param {number} courseId - 课程 ID
 * @param {string} planId - 计划 UUID
 */
export function publishPlan(courseId, planId) {
  return request.post(`/visualization/course/${courseId}/${planId}/publish`)
}
