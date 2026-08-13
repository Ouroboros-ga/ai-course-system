import { onBeforeUnmount, ref } from 'vue'
import { queryAsrResult, submitAsrTranscribe } from '@/api/asr.js'
import { showToast } from '@/utils/toast'

/**
 * 语音输入 composable：浏览器麦克风录音 → 上传后端 → 豆包 ASR 转写 → 文本回调。
 *
 * 状态机：idle → recording → transcribing → idle。
 * - start()  请求麦克风权限并开始录音（录音中再次调用无效）
 * - stop()   停止录音并自动进入转写流程
 * - cancel() 丢弃本次录音，不发起转写
 *
 * @param {Object} options
 * @param {(text: string) => void} [options.onText] 转写成功回调（文本已去除首尾空白）
 * @param {() => (string|number|null)} [options.getCourseId] 提交时返回当前课程 ID
 */
export function useVoiceInput({ onText, getCourseId } = {}) {
  const status = ref('idle') // idle | recording | transcribing
  const errorMessage = ref('')
  const durationMs = ref(0)

  const supported = typeof window !== 'undefined'
    && !!(navigator.mediaDevices?.getUserMedia)
    && !!(window.MediaRecorder)

  const MAX_RECORD_MS = 120 * 1000 // 与后端 ASR_MAX_DURATION_SECONDS 对齐
  const POLL_INTERVAL_MS = 3000
  const MAX_POLLS = 20 // 最长约 60s 轮询

  let mediaRecorder = null
  let mediaStream = null
  let chunks = []
  let recordStartedAt = 0
  let recordTimer = null
  let discardRecording = false

  const sleep = (ms) => new Promise(resolve => window.setTimeout(resolve, ms))

  function cleanupTracks() {
    if (mediaStream) {
      mediaStream.getTracks().forEach(track => track.stop())
      mediaStream = null
    }
  }

  function clearRecordTimer() {
    if (recordTimer) {
      window.clearInterval(recordTimer)
      recordTimer = null
    }
    durationMs.value = 0
  }

  async function start() {
    if (status.value === 'recording' || status.value === 'transcribing') return false
    errorMessage.value = ''
    if (!supported) {
      errorMessage.value = '当前浏览器不支持语音输入，请使用新版 Chrome / Edge / Firefox'
      showToast(errorMessage.value, 'error')
      return false
    }

    chunks = []
    discardRecording = false
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (err) {
      errorMessage.value = '无法访问麦克风，请检查浏览器权限设置'
      showToast(errorMessage.value, 'error')
      cleanupTracks()
      return false
    }

    try {
      mediaRecorder = new MediaRecorder(mediaStream)
      mediaRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) chunks.push(event.data)
      }
      mediaRecorder.onstop = () => {
        clearRecordTimer()
        cleanupTracks()
        if (discardRecording) {
          status.value = 'idle'
          return
        }
        void transcribe(chunks)
      }
      mediaRecorder.start()
    } catch (err) {
      errorMessage.value = '录音初始化失败，请重试'
      showToast(errorMessage.value, 'error')
      cleanupTracks()
      return false
    }

    status.value = 'recording'
    recordStartedAt = Date.now()
    recordTimer = window.setInterval(() => {
      durationMs.value = Date.now() - recordStartedAt
      if (durationMs.value >= MAX_RECORD_MS) stop() // 超过上限自动停止
    }, 250)
    return true
  }

  function stop() {
    if (status.value !== 'recording' || !mediaRecorder) return
    try {
      mediaRecorder.stop()
    } catch (err) {
      // 罕见竞态：stop 前 recorder 已结束
      clearRecordTimer()
      cleanupTracks()
      status.value = 'idle'
    }
  }

  function cancel() {
    discardRecording = true
    stop()
  }

  async function transcribe(recordedChunks) {
    const blob = new Blob(recordedChunks, { type: (mediaRecorder && mediaRecorder.mimeType) || 'audio/webm' })
    if (!blob.size) {
      status.value = 'idle'
      errorMessage.value = '录音内容为空，请重试'
      showToast(errorMessage.value, 'error')
      return
    }

    const courseId = typeof getCourseId === 'function' ? getCourseId() : null
    if (courseId == null || courseId === '') {
      status.value = 'idle'
      errorMessage.value = '课程信息尚未就绪，无法提交语音转写'
      showToast(errorMessage.value, 'error')
      return
    }

    status.value = 'transcribing'
    try {
      const submitted = await submitAsrTranscribe(blob, courseId)
      const taskId = submitted && submitted.task_id
      if (!taskId) throw new Error('语音转写任务提交失败')

      for (let attempt = 0; attempt < MAX_POLLS; attempt++) {
        await sleep(POLL_INTERVAL_MS)
        const result = await queryAsrResult(taskId)
        if (result.status === 'completed') {
          status.value = 'idle'
          const text = String(result.text || '').trim()
          if (text) {
            if (typeof onText === 'function') onText(text)
          } else {
            errorMessage.value = '未能识别到有效语音，请重试'
            showToast(errorMessage.value, 'error')
          }
          return
        }
        if (result.status === 'failed') {
          status.value = 'idle'
          errorMessage.value = result.message || '语音转写失败'
          showToast(errorMessage.value, 'error')
          return
        }
        // processing / queued：继续轮询
      }
      status.value = 'idle'
      errorMessage.value = '语音转写超时，请稍后重试'
      showToast(errorMessage.value, 'error')
    } catch (err) {
      status.value = 'idle'
      errorMessage.value = err.message || '语音转写失败，请稍后重试'
      showToast(errorMessage.value, 'error')
    }
  }

  onBeforeUnmount(() => {
    if (status.value === 'recording') {
      discardRecording = true
      try {
        mediaRecorder && mediaRecorder.stop()
      } catch (err) {
        // 忽略卸载时的停止异常
      }
    }
    clearRecordTimer()
    cleanupTracks()
  })

  return {
    status,
    errorMessage,
    durationMs,
    supported,
    start,
    stop,
    cancel,
  }
}
