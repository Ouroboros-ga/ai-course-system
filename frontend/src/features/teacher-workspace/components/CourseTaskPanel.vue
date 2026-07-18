<template>
  <section class="course-tasks" aria-labelledby="course-task-heading">
    <header class="task-heading">
      <div><p class="eyebrow">课程级状态</p><h2 id="course-task-heading">生成任务</h2></div>
      <button type="button" class="refresh-button" :disabled="loading" @click="refresh"><RefreshCw :size="15" />{{ loading ? '刷新中' : '刷新' }}</button>
    </header>

    <p v-if="loadError" class="task-error"><AlertTriangle :size="16" />{{ loadError }}</p>
    <div v-else-if="loading && !tasks.length" class="task-empty"><LoaderCircle class="spin" :size="17" />正在读取课程任务…</div>
    <div v-else-if="!tasks.length" class="task-empty">当前没有可追踪的后台任务。生成任务开始后，这里会持续显示最新状态。</div>
    <div v-else class="task-list">
      <LongTaskCard v-for="task in tasks" :key="task.id" :task="task" :loading="retryingIds.has(task.id)" @refresh="refresh" @retry="retry(task)" @confirm="confirm(task)" />
    </div>

    <div class="task-footer">
      <p><Info :size="15" />任务状态来自现有 TTS 与数字人接口；离开页面后重新进入仍会重新读取。</p>
      <button v-if="showVideoGeneration" type="button" class="video-button" :disabled="startingVideo" @click="startVideo"><Video :size="15" />{{ startingVideo ? '正在提交…' : '生成课程数字人视频' }}</button>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { AlertTriangle, Info, LoaderCircle, RefreshCw, Video } from 'lucide-vue-next'
import LongTaskCard from './LongTaskCard.vue'
import { getCourseTtsStatus, getCourseVideoTasks, generateCourseVideos } from '@/api/generation_tasks.js'
import { normalizeLongTask } from '../taskStatus.js'
import { showToast } from '@/utils/toast.js'

const props = defineProps({ courseId: { type: [Number, String], required: true }, showVideoGeneration: Boolean })
const emit = defineEmits(['summary', 'open-legacy'])
const tasks = ref([]); const loading = ref(false); const loadError = ref(''); const startingVideo = ref(false); const retryingIds = ref(new Set()); const confirmedIds = ref(new Set()); let timerId = null

function ttsTask(payload) {
  const status = String(payload?.status || 'not_started').toLowerCase()
  const errors = Array.isArray(payload?.errors) ? payload.errors : []
  return normalizeLongTask({
    id: `tts-${props.courseId}`,
    title: '课程 TTS 语音',
    status,
    total: payload?.total || 0,
    completed: payload?.completed || 0,
    error: errors.map(item => item.error || item.message || String(item)).filter(Boolean).join('；'),
    message: payload?.message,
    requires_confirmation: ['completed', 'partial'].includes(status),
  })
}

function videoTasks(payload) {
  const rawTasks = Array.isArray(payload?.tasks) ? payload.tasks : []
  return rawTasks.map(item => normalizeLongTask({
    ...item,
    id: `video-${item.id}`,
    title: item.node_id ? `知识点 ${item.node_id} 的数字人视频` : '课程数字人视频',
    requires_confirmation: ['completed', 'succeeded'].includes(String(item.status).toLowerCase()),
  }))
}

const summary = computed(() => ({
  total: tasks.value.length,
  running: tasks.value.filter(task => task.status === 'running').length,
  blocking: tasks.value.filter(task => ['failed', 'timeout', 'partial_success'].includes(task.status)).length,
  review: tasks.value.filter(task => task.requiresReview && !confirmedIds.value.has(task.id)).length,
}))

async function refresh() {
  loading.value = true; loadError.value = ''
  try {
    const [tts, video] = await Promise.all([getCourseTtsStatus(props.courseId), getCourseVideoTasks(props.courseId)])
    const newTasks = []
    if (tts) newTasks.push(ttsTask(tts))
    newTasks.push(...videoTasks(video))
    tasks.value = newTasks
    emit('summary', { ...summary.value, known: true })
  } catch {
    loadError.value = '课程任务暂时无法读取。不会隐藏已有失败；请检查网络、课程权限或相关服务后重试。'
    emit('summary', { ...summary.value, known: false })
  } finally { loading.value = false }
}

async function startVideo() {
  startingVideo.value = true
  try {
    await generateCourseVideos(props.courseId, { force: false })
    showToast('数字人视频任务已提交，可离开此页后回来查看。', 'success')
    await refresh()
  } catch { showToast('提交数字人视频任务失败，请检查脚本、素材与数字人服务后重试。', 'error') } finally { startingVideo.value = false }
}

async function retry(task) {
  if (!task.id.startsWith('video-')) {
    showToast('当前后端未提供课程级 TTS 重试接口；请在原编辑器重新发起生成。', 'info')
    emit('open-legacy')
    return
  }
  const source = tasks.value.find(item => item.id === task.id)
  const nodeId = Number(source?.source?.node_id)
  retryingIds.value = new Set([...retryingIds.value, task.id])
  try {
    await generateCourseVideos(props.courseId, { node_ids: Number.isFinite(nodeId) ? [nodeId] : undefined, force: true })
    showToast('已重新提交数字人视频任务。', 'success'); await refresh()
  } catch { showToast('重新提交失败，请检查数字人服务后重试。', 'error') } finally { const next = new Set(retryingIds.value); next.delete(task.id); retryingIds.value = next }
}

function confirm(task) { const next = new Set(confirmedIds.value); next.add(task.id); confirmedIds.value = next; showToast('已标记为本次会话已检查。当前后端尚未提供教师确认的持久化接口。', 'info'); emit('summary', { ...summary.value, known: true }) }
onMounted(() => { refresh(); timerId = window.setInterval(refresh, 10000) })
onBeforeUnmount(() => { if (timerId) window.clearInterval(timerId) })
</script>

<style scoped>
.course-tasks{margin-top:16px;padding-top:16px;border-top:1px solid #e2e8f0}.task-heading{display:flex;align-items:center;justify-content:space-between;gap:8px}.eyebrow{margin:0;color:#64748b;font-size:11px}.task-heading h2{margin:3px 0 0;font-size:15px;color:#1e293b}.refresh-button,.video-button{min-height:34px;border-radius:7px;padding:0 9px;display:inline-flex;align-items:center;gap:5px;font-size:12px;cursor:pointer}.refresh-button{border:1px solid #cbd5e1;background:#fff;color:#334155}.video-button{border:1px solid #1769aa;background:#1769aa;color:#fff}.refresh-button:disabled,.video-button:disabled{opacity:.55;cursor:not-allowed}.task-list{display:grid;gap:9px;margin-top:12px;max-height:420px;overflow:auto;padding-right:2px}.task-empty{min-height:82px;display:flex;align-items:center;justify-content:center;text-align:center;color:#64748b;font-size:12px;line-height:1.5}.task-error{margin:12px 0 0;border-radius:7px;background:#fef2f2;color:#991b1b;padding:9px;display:flex;gap:6px;align-items:flex-start;font-size:12px;line-height:1.45}.task-footer{margin-top:12px;color:#64748b;font-size:12px;line-height:1.5}.task-footer p{margin:0;display:flex;gap:5px}.video-button{margin-top:10px}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}button:focus-visible{outline:3px solid #93c5fd;outline-offset:2px}@media(prefers-reduced-motion:reduce){.spin{animation:none}}
</style>
