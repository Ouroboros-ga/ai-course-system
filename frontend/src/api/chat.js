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
    params: {
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
  return request({
    url: '/chat/file/upload',
    method: 'post',
    headers: {
      'Content-Type': 'multipart/form-data'
    },
    data: formData
  })
}
