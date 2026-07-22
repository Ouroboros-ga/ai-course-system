import request from '@/utils/request.js'

const flat = { allowFlatResponse: true }

export function getRetrievalDemoStatus() {
  return request({ url: '/retrieval-demo/status', method: 'get', ...flat })
}

export function getRetrievalDemoCourses() {
  return request({ url: '/retrieval-demo/courses', method: 'get', ...flat })
}

export function getRetrievalDemoPresets(courseId) {
  return request({ url: `/retrieval-demo/courses/${encodeURIComponent(courseId)}/presets`, method: 'get', ...flat })
}

export function getRetrievalDemoGraph(courseId) {
  return request({ url: `/retrieval-demo/courses/${encodeURIComponent(courseId)}/graph`, method: 'get', ...flat })
}

export function runRetrievalDemo(payload) {
  return request({ url: '/retrieval-demo/query', method: 'post', data: payload, ...flat })
}

export function rollbackRetrievalDemo() {
  return request({ url: '/retrieval-demo/rollback', method: 'post', data: {}, ...flat })
}
