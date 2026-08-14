import request from '@/utils/request.js'

/**
 * Legacy history surface used only by the still-routed /chat page. New
 * learning workspaces keep their conversation state locally and must not add
 * dependencies on this endpoint.
 */
export function getChatHistory(params = {}) {
  return request({
    url: '/chat/history',
    method: 'get',
    params: {
      userId: params.userId,
      page: params.page || 1,
      pageSize: params.pageSize || 20,
    },
  })
}

/**
 * Compatibility alias for the legacy teacher/chat upload surfaces. It is not
 * a new integration point; use the course-import APIs in document.js for new
 * work.
 */
export function uploadFile(formData) {
  const token = localStorage.getItem('token')
  const headers = { 'Content-Type': 'multipart/form-data' }
  if (token) headers.Authorization = `Bearer ${token}`

  return request({
    url: '/chat/file/upload',
    method: 'post',
    headers,
    data: formData,
  })
}

/**
 * V1 availability fallback for TeachingAgent. Keep this client until a
 * replacement offers the same failure semantics.
 */
export function askQuestion(data) {
  return request({
    url: '/chat/ask',
    method: 'post',
    data: {
      question: data.question,
      chatId: data.chatId || null,
      courseId: data.courseId || null,
      currentNodeId: data.currentNodeId || null,
      sessionId: data.sessionId || null,
    },
  })
}
