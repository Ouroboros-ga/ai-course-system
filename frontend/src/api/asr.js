import request from '@/utils/request.js'

/**
 * 豆包语音输入（ASR）API
 *
 * 端点前缀：/api/v1/asr
 * 流程：浏览器录音 → 上传 /asr/transcribe 提交转写任务 → 轮询 /asr/result 取文本。
 */

/**
 * 上传录音并提交语音转写任务。
 * POST /asr/transcribe（multipart：file + course_id）
 *
 * @param {File|Blob} file - 录音文件（MediaRecorder 输出的 webm/ogg/wav 等）
 * @param {string|number} courseId - 课程 ID（用于签发课程权限签名的音频 URL）
 * @returns {Promise<{task_id: string, status: string}>}
 */
export function submitAsrTranscribe(file, courseId) {
  const formData = new FormData()
  formData.append('file', file, 'voice-input.webm')
  formData.append('course_id', String(courseId))
  return request({
    url: '/asr/transcribe',
    method: 'post',
    data: formData,
    timeout: 60000,
  })
}

/**
 * 查询语音转写结果。
 * POST /asr/result
 *
 * @param {string} taskId - submitAsrTranscribe 返回的 task_id
 * @returns {Promise<{status: 'completed'|'processing'|'queued'|'failed', text?: string, message?: string}>}
 */
export function queryAsrResult(taskId) {
  return request({
    url: '/asr/result',
    method: 'post',
    data: { task_id: taskId },
    timeout: 60000,
  })
}
