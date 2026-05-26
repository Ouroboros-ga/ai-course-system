import request from '@/utils/request.js'

/**
 * 获取用户全部历史对话记录（分页）
 * @param {Object} params - 请求参数
 * @param {number} params.userId - 用户ID（必填）
 * @param {number} [params.page=1] - 页码，默认第 1 页
 * @param {number} [params.pageSize=20] - 每页数量，默认 20 条，最大 100
 */
export function getChatHistory(params = {}) {
  return request({
    url: '/chat/history',
    method: 'get',
    params: {
      userId: params.userId,
      page: params.page || 1,
      pageSize: params.pageSize || 20
    }
  })
}

/**
 * 创建新的聊天记录
 * @param {Object} params - 请求参数
 * @param {number} params.userId - 用户ID
 * @param {string} params.content - 聊天内容
 */
export function createChatRecord(params) {
  return request({
    url: '/chat/create',
    method: 'post',
    data: {
      userId: params.userId,
      content: params.content
    }
  })
}

/**
 * 删除聊天记录
 * @param {number} chatId - 聊天记录ID
 * @param {number} userId - 用户ID
 */
export function deleteChatRecord(chatId, userId) {
  return request({
    url: `/chat/${chatId}`,
    method: 'delete',
    params: {
      userId: userId
    }
  })
}

/**
 * 用户上传文件（图片、文档等）
 * 后端自动解析内容、生成摘要和 TTS 语音，创建/关联会话
 * @param {FormData} formData - FormData 对象，包含：
 *   - file: 上传的文件
 *   - fileName: 文件名称
 *   - userId: 用户 ID
 */
export function uploadFile(formData) {
  const token = localStorage.getItem('token')
  const headers = {
    'Content-Type': 'multipart/form-data'
  }
  
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  
  return request({
    url: '/chat/file/upload',
    method: 'post',
    headers: headers,
    data: formData
  })
}

/**
 * AI问答接口
 * @param {Object} data - 请求参数
 * @param {string} data.question - 用户问题（必填）
 * @param {number} [data.chatId] - 会话ID，不传则创建新会话
 * @param {number} [data.courseId] - 课程ID，用于基于文档问答
 * @param {number} [data.currentNodeId] - 当前学习节点ID，用于理解度分析
 * @returns {Promise} 返回AI回答和理解度分析
 */
export function askQuestion(data) {
  return request({
    url: '/chat/ask',
    method: 'post',
    data: {
      question: data.question,
      chatId: data.chatId || null,
      courseId: data.courseId || null,
      currentNodeId: data.currentNodeId || null
    }
  })
}

/**
 * 获取会话中的所有消息
 * @param {number} chatId - 会话ID
 * @returns {Promise} 返回消息列表
 */
export function getChatMessages(chatId) {
  return request({
    url: `/chat/messages/${chatId}`,
    method: 'get'
  })
}
