<script setup>
import { computed, ref } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { FileUp, ShieldCheck } from 'lucide-vue-next'
import { createCourseImport } from '@/api/document.js'
import { useCounterStore } from '@/stores/counter.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'

const router = useRouter()
const counter = useCounterStore()
const selectedFile = ref(null)
const inputRef = ref(null)
const phase = ref('select') // select | uploading | accepted | error
const uploadPercent = ref(0)
const error = ref('')
const importRecord = ref(null)
const canSubmit = computed(() => Boolean(selectedFile.value) && phase.value !== 'uploading')

function chooseFile() { inputRef.value?.click() }
function onFileChange(event) {
  selectedFile.value = event.target.files?.[0] ?? null
  error.value = ''
  phase.value = 'select'
}

function localImportKey() {
  return `course-import:${counter.userData?.id ?? counter.userData?.user_id ?? 'current'}`
}

async function submit() {
  if (!canSubmit.value) return
  phase.value = 'uploading'
  error.value = ''
  uploadPercent.value = 0
  try {
    const data = await createCourseImport(selectedFile.value, {
      onUploadProgress: (event) => {
        if (event.total) uploadPercent.value = Math.round((event.loaded / event.total) * 100)
      },
    })
    if (!data?.course_id || !data?.task_id) throw new Error('服务器没有返回课程或任务标识。')
    importRecord.value = data
    localStorage.setItem(localImportKey(), JSON.stringify({
      course_id: data.course_id,
      task_id: data.task_id,
      run_id: data.run_id,
      created_at: new Date().toISOString(),
    }))
    phase.value = 'accepted'
  } catch (caught) {
    error.value = caught?.response?.data?.detail || caught?.message || '创建课程失败，请检查文件后重试。'
    phase.value = 'error'
  }
}

function continueBuild() {
  if (!importRecord.value?.course_id) return
  router.push(`/app/course/${importRecord.value.course_id}/build/materials`)
}
function goBuilding() { router.push('/app/courses/building') }

onBeforeRouteLeave(() => {
  if (phase.value === 'uploading') {
    return window.confirm('文件仍在上传，离开会中断本次上传。确定离开吗？')
  }
  return true
})
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header"><div><h1 class="sfx-t-title1"><FileUp :size="25" /> 创建课程</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">上传一份课程源文件，先创建草稿课程，再由后台持续完成解析。</p></div></header>

    <section v-if="phase !== 'accepted'" class="sfx-panel create-panel">
      <div class="create-intro"><ShieldCheck :size="25" /><div><h2 class="sfx-panel-title">选择课程材料</h2><p class="sfx-t-ui sfx-t-secondary">支持 PPT、PPTX、PDF、DOC、DOCX，单个文件最大 50MB。系统先保存文件、草稿课程与解析任务；收到“已创建”后可安全离开页面。</p></div></div>
      <input ref="inputRef" class="sr-only" type="file" accept=".ppt,.pptx,.pdf,.doc,.docx" :disabled="phase === 'uploading'" @change="onFileChange" />
      <div class="file-box"><div><strong class="sfx-t-ui">{{ selectedFile?.name || '尚未选择文件' }}</strong><p v-if="selectedFile" class="sfx-t-caption sfx-t-secondary">{{ Math.ceil(selectedFile.size / 1024) }} KB</p></div><SfxButton variant="secondary" :disabled="phase === 'uploading'" @click="chooseFile">选择文件</SfxButton></div>
      <div v-if="phase === 'uploading'" class="upload-status" aria-live="polite"><div><strong>正在上传到课程工作区</strong><span>{{ uploadPercent }}%</span></div><progress :value="uploadPercent" max="100" /><p class="sfx-t-ui sfx-t-secondary">上传尚未完成前请不要离开此页；文件上传完成后，解析任务会独立于浏览器持续执行。</p></div>
      <SfxError v-if="phase === 'error'" :description="error" @retry="submit" />
      <div class="create-actions"><SfxButton variant="tertiary" :disabled="phase === 'uploading'" @click="goBuilding">返回我建设的</SfxButton><SfxButton variant="primary" :disabled="!canSubmit" :loading="phase === 'uploading'" @click="submit">创建草稿课程</SfxButton></div>
    </section>

    <section v-else class="sfx-panel accepted-panel" aria-live="polite"><ShieldCheck :size="31" /><div><h2 class="sfx-t-title2">草稿课程已创建</h2><p class="sfx-t-ui sfx-t-secondary">材料与解析任务已持久化。你现在可以离开此页；解析会在后台继续，结果可在“我建设的”或任务中心查看。</p><dl class="sfx-desc"><dt>课程状态</dt><dd>草稿（不会出现在课程大厅，也不能设置加入码）</dd><dt>解析任务</dt><dd class="sfx-mono">{{ importRecord?.task_id }}</dd></dl></div><div class="create-actions"><SfxButton variant="secondary" @click="goBuilding">查看我建设的</SfxButton><SfxButton variant="primary" @click="continueBuild">进入课程建设</SfxButton></div></section>
  </div>
</template>

<style scoped>
.create-panel, .accepted-panel { display: flex; flex-direction: column; align-items: flex-start; gap: var(--space-4); }
.create-intro { display:flex; align-items:flex-start; gap:var(--space-3); color:var(--ink-700); }
.create-intro p { margin-top: var(--space-2); line-height: 1.65; }
.file-box { width:100%; display:flex; align-items:center; justify-content:space-between; gap:var(--space-3); padding:var(--space-4); border:1px dashed var(--border-strong); border-radius:var(--radius-md); }
.file-box p { margin:var(--space-1) 0 0; }
.upload-status { width:100%; display:grid; gap:var(--space-2); padding:var(--space-3); border-radius:var(--radius-md); background:var(--surface-cool); }
.upload-status > div { display:flex; justify-content:space-between; }
.upload-status progress { width:100%; }
.upload-status p { margin:0; }
.create-actions { display:flex; justify-content:flex-end; gap:var(--space-2); width:100%; }
.accepted-panel { max-width:760px; }
.accepted-panel > svg { color:var(--green-700); }
.sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0, 0, 0, 0); white-space:nowrap; border:0; }
@media (max-width: 640px) { .file-box, .create-actions { align-items:stretch; flex-direction:column; } }
</style>
