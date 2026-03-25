import request from '@/utils/request.js'

/**
 * 获取用户全部历史对话记录（分页）
 * @param {Object} data - 请求参数
 * @param {number} [data.page=1] - 页码，默认第 1 页
 * @param {number} [data.pageSize=20] - 每页数量，默认 20 条，最大 100
 */
export function getChatHistory(data = {}) {
  return request({
    url: '/chat/history',
    method: 'post',
    data: {
      page: data.page || 1,
      pageSize: data.pageSize || 20
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

