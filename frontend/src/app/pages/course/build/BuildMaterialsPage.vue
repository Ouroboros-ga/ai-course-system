<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { FilePlus2, RefreshCw, Upload } from 'lucide-vue-next'
import { listBuildMaterials, uploadCourseMaterials } from '@/api/course_build.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const inputRef = ref(null)
const loading = ref(true)
const error = ref('')
const uploadError = ref('')
const materials = ref([])
const pendingFiles = ref([])
const uploading = ref(false)
const uploadPercent = ref(0)
let pollTimer = null

const roleOptions = [
  ['primary_courseware', '主课件'],
  ['textbook', '教材'],
  ['syllabus', '课程大纲'],
  ['experiment_guide', '实验指导'],
  ['exercise_bank', '习题集'],
  ['reference', '参考材料'],
]
const statusLabel = {
  uploaded: '等待解析', parsing: '正在解析', parsed: '解析成功', needs_review: '需要人工检查', failed: '解析失败', superseded: '已被新版本替代',
}
const roleLabel = Object.fromEntries(roleOptions)
const terminalStates = new Set(['parsed', 'needs_review', 'failed', 'superseded'])
const progressText = computed(() => {
  const done = materials.value.filter((item) => terminalStates.has(item.status)).length
  return `${done}/${materials.value.length} 份资料已完成处理`
})

function suggestedRole(file) {
  const name = file.name.toLowerCase()
  if (name.endsWith('.ppt') || name.endsWith('.pptx')) return 'primary_courseware'
  if (name.endsWith('.pdf')) return 'textbook'
  return 'reference'
}
function chooseFiles() { inputRef.value?.click() }
function selectFiles(event) {
  const chosen = Array.from(event.target.files || [])
  pendingFiles.value.push(...chosen.map((file) => ({
    id: `${file.name}:${file.size}:${file.lastModified}:${crypto.randomUUID()}`,
    file,
    role: suggestedRole(file),
  })))
  event.target.value = ''
  uploadError.value = ''
}
function removePending(id) { pendingFiles.value = pendingFiles.value.filter((item) => item.id !== id) }
async function load({ quiet = false } = {}) {
  if (!quiet) loading.value = true
  error.value = ''
  try {
    const data = await listBuildMaterials(courseId.value)
    materials.value = data?.items ?? []
  } catch (err) {
    error.value = err?.message || '资料读取失败'
  } finally {
    if (!quiet) loading.value = false
  }
}
async function upload() {
  if (!pendingFiles.value.length || uploading.value) return
  uploading.value = true
  uploadError.value = ''
  uploadPercent.value = 0
  try {
    await uploadCourseMaterials(courseId.value, pendingFiles.value, (event) => {
      if (event.total) uploadPercent.value = Math.round((event.loaded / event.total) * 100)
    })
    pendingFiles.value = []
    await load({ quiet: true })
    startPolling()
  } catch (err) {
    uploadError.value = err?.message || '材料上传失败，请检查文件后重试。'
  } finally {
    uploading.value = false
  }
}
function startPolling() {
  window.clearInterval(pollTimer)
  if (materials.value.some((item) => !terminalStates.has(item.status))) {
    pollTimer = window.setInterval(async () => {
      await load({ quiet: true })
      if (!materials.value.some((item) => !terminalStates.has(item.status))) window.clearInterval(pollTimer)
    }, 4000)
  }
}
onMounted(async () => { await load(); startPolling() })
onBeforeUnmount(() => window.clearInterval(pollTimer))
</script>

<template>
  <section class="stage">
    <header class="stage-head">
      <div><p class="eyebrow">Step 1</p><h1>课程资料</h1><p class="muted">连续上传课件、教材或实验指导。每份材料独立保存并进入解析队列，不必等待上一份完成。</p></div>
      <SfxButton variant="secondary" size="sm" :loading="loading" @click="load"><RefreshCw :size="15" /> 刷新状态</SfxButton>
    </header>

    <section class="upload-panel" aria-labelledby="upload-title">
      <div class="upload-copy"><FilePlus2 :size="22" /><div><h2 id="upload-title" class="sfx-panel-title">添加课程材料</h2><p class="sfx-t-caption sfx-t-secondary">支持 PPT、PPTX、PDF、DOC、DOCX；单份最大 50MB。可为每份资料指定教学角色。</p></div></div>
      <input ref="inputRef" class="sr-only" type="file" multiple accept=".ppt,.pptx,.pdf,.doc,.docx" :disabled="uploading" @change="selectFiles" />
      <SfxButton variant="secondary" :disabled="uploading" @click="chooseFiles"><Upload :size="16" /> 选择文件</SfxButton>
      <div v-if="pendingFiles.length" class="pending-list">
        <article v-for="item in pendingFiles" :key="item.id" class="pending-file"><div><strong>{{ item.file.name }}</strong><p class="sfx-t-caption sfx-t-secondary">{{ Math.ceil(item.file.size / 1024) }} KB</p></div><label class="sfx-t-caption">材料角色<select v-model="item.role" class="sfx-select"><option v-for="option in roleOptions" :key="option[0]" :value="option[0]">{{ option[1] }}</option></select></label><button class="remove" type="button" :disabled="uploading" :aria-label="`移除 ${item.file.name}`" @click="removePending(item.id)">移除</button></article>
      </div>
      <div v-if="uploading" class="upload-status" role="status"><span>正在上传 {{ pendingFiles.length }} 份材料</span><strong>{{ uploadPercent }}%</strong><progress :value="uploadPercent" max="100" /></div>
      <p v-if="uploadError" class="error" role="alert">{{ uploadError }}</p>
      <div class="upload-actions"><SfxButton variant="primary" :disabled="!pendingFiles.length" :loading="uploading" @click="upload">保存并开始解析</SfxButton></div>
    </section>

    <SfxError v-if="!loading && error" :description="error" @retry="load" />
    <template v-else>
      <div class="materials-head"><h2 class="sfx-t-title3">已上传资料</h2><span class="sfx-t-caption sfx-t-secondary">{{ progressText }}</span></div>
      <p v-if="loading" class="empty">正在读取资料…</p>
      <div v-else-if="!materials.length" class="empty">还没有课程资料。添加主课件、教材或其他教学材料后，解析会在后台继续执行。</div>
      <div v-else class="materials">
        <article v-for="item in materials" :key="item.material_id" class="material"><div><strong>{{ item.name }}</strong><p class="sfx-t-caption sfx-t-secondary">{{ roleLabel[item.material_role] || item.material_role || '参考材料' }} · {{ item.material_type }}</p></div><span class="status" :class="`status-${item.status}`">{{ statusLabel[item.status] || item.status }}</span><small>当前版本：{{ item.current_version_id || '—' }}</small></article>
      </div>
    </template>
  </section>
</template>

<style scoped>
.stage{background:#fff;border:1px solid #dbe2ea;border-radius:12px;padding:24px;min-height:520px}.stage-head{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}.eyebrow,.muted,small{color:#64748b;font-size:13px}.eyebrow{margin:0 0 4px}h1{margin:0 0 10px}.muted{margin:0;line-height:1.6}.upload-panel{margin:24px 0;border:1px solid #cbd5e1;border-radius:10px;padding:16px;display:grid;gap:14px}.upload-copy{display:flex;gap:10px;color:#334155}.upload-copy p{margin:4px 0 0}.pending-list,.materials{display:grid;gap:10px}.pending-file,.material{display:grid;grid-template-columns:minmax(0,1fr) 170px auto;align-items:center;gap:14px;border:1px solid #e2e8f0;border-radius:9px;padding:12px}.pending-file p,.material p{margin:4px 0 0}.pending-file label{display:grid;gap:4px}.remove{border:0;background:transparent;color:#b91c1c;cursor:pointer;font-size:13px}.upload-status{display:grid;grid-template-columns:1fr auto;gap:8px;color:#334155}.upload-status progress{grid-column:1/-1;width:100%}.upload-actions{display:flex;justify-content:flex-end}.materials-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin:24px 0 12px}.materials-head h2{margin:0}.material small{justify-self:end}.status{font-size:13px;font-weight:600;color:#475569}.status-parsing{color:#0369a1}.status-parsed{color:#15803d}.status-failed{color:#b91c1c}.status-uploaded{color:#a16207}.empty{padding:48px;text-align:center;color:#64748b}.error{margin:0;color:#b91c1c}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@media(max-width:720px){.stage-head,.materials-head{align-items:stretch;flex-direction:column}.pending-file,.material{grid-template-columns:1fr}.material small{justify-self:start}.upload-actions{justify-content:stretch}.upload-actions :deep(button){width:100%}}
.status-needs_review{color:#a16207}
</style>
