import request from '@/utils/request.js'

/**
 * OJ 题库 / 活动 / 榜 API（PR-10/08/11 前端接入）。
 * 全部挂在既有前缀 /api/v1/experiments 下（ADR-0001 决定 6，不引入 /oj）。
 * request 拦截器对统一信封 {code,message,data} 自动解包，这里直接返回 data。
 */

const courseBase = (courseId) => `/api/v1/experiments/course/${courseId}`

// ── 学生题库 façade（PR-10） ──

export const listOJProblems = (courseId, params = {}) =>
  request.get(`${courseBase(courseId)}/problems`, { params })

export const getOJProblem = (courseId, experimentId) =>
  request.get(`${courseBase(courseId)}/problems/${experimentId}`)

export const listOJSubmissions = (courseId, params = {}) =>
  request.get(`${courseBase(courseId)}/submissions`, { params })

export const getOJSubmission = (courseId, runId) =>
  request.get(`${courseBase(courseId)}/submissions/${runId}`)

// ── Activity 管理（PR-08，教师侧） ──

export const listOJActivities = (courseId) =>
  request.get(`${courseBase(courseId)}/activities`)

export const getOJActivity = (courseId, activityId) =>
  request.get(`${courseBase(courseId)}/activities/${activityId}`)

export const createOJActivity = (courseId, payload) =>
  request.post(`${courseBase(courseId)}/activities`, payload)

export const updateOJActivity = (courseId, activityId, payload) =>
  request.put(`${courseBase(courseId)}/activities/${activityId}`, payload)

export const publishOJActivity = (courseId, activityId) =>
  request.post(`${courseBase(courseId)}/activities/${activityId}/publish`)

export const archiveOJActivity = (courseId, activityId) =>
  request.post(`${courseBase(courseId)}/activities/${activityId}/archive`)

export const addOJActivityProblem = (courseId, activityId, payload) =>
  request.post(`${courseBase(courseId)}/activities/${activityId}/problems`, payload)

export const removeOJActivityProblem = (courseId, activityId, ordinal) =>
  request.delete(`${courseBase(courseId)}/activities/${activityId}/problems/${ordinal}`)

export const setOJActivityScopes = (courseId, activityId, scopes) =>
  request.put(`${courseBase(courseId)}/activities/${activityId}/scopes`, { scopes })

// ── 计分板（PR-11，教师侧） ──

export const getOJScoreboard = (courseId, activityId) =>
  request.get(`${courseBase(courseId)}/activities/${activityId}/scoreboard`)

// ── 学生侧活动（PR-12） ──

export const listOJStudentActivities = (courseId) =>
  request.get(`${courseBase(courseId)}/student/activities`)

// ── 学情看板聚合（PR-14 缩范围，教师侧） ──

export const getOJAnalytics = (courseId, trendDays = 30) =>
  request.get(`${courseBase(courseId)}/analytics/oj`, { params: { trend_days: trendDays } })

// ── 教师评测记录（课程全量提交流水） ──

export const listOJCourseSubmissions = (courseId, params = {}) =>
  request.get(`${courseBase(courseId)}/submissions`, { params })
