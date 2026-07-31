<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { FilePlus2, Upload } from 'lucide-vue-next'
import { getDraftBuildStatus, listBuildMaterials, uploadCourseMaterials } from '@/api/course_build.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const workbench = inject('courseBuildWorkbench', null)
const inputRef = ref(null)
const loading = ref(true)
const error = ref('')
const uploadError = ref('')
const materials = ref([])
const draftBuild = ref(null)
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
const hasUnfinishedMaterials = computed(() => materials.value.some((item) => !terminalStates.has(item.status)))
const needsPolling = computed(() => (
  hasUnfinishedMaterials.value
  || ['assembling_corpus', 'submitting_build', 'building'].includes(draftBuild.value?.phase)
))
const draftBuildText = computed(() => {
  switch (draftBuild.value?.phase) {
    case 'parsing_materials': return '课程资料正在解析；全部材料完成后将自动启动智能备课。'
    case 'assembling_corpus': return '资料解析完成，正在汇总课程材料。'
    case 'submitting_build': return '课程材料已汇总，正在提交智能备课任务。'
    case 'building': return '备课智能体正在整理课程结构、讲授脚本和候选知识图谱。'
    case 'ready_for_review': return '智能备课完成，课程草稿已进入教师审核。'
    case 'blocked_by_materials': return draftBuild.value?.error_message || '有材料需要处理后才能自动备课。'
    case 'build_failed': return `智能备课失败：${draftBuild.value?.error_message || '请在任务中心查看失败原因。'}`
    case 'build_cancelled': return '材料版本已变化，系统将基于最新材料自动重新汇总。'
    default: return ''
  }
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
    const [data, buildStatus] = await Promise.all([
      listBuildMaterials(courseId.value),
      getDraftBuildStatus(courseId.value),
    ])
    materials.value = data?.items ?? []
    draftBuild.value = buildStatus ?? null
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
  if (needsPolling.value) {
    pollTimer = window.setInterval(async () => {
      await load({ quiet: true })
      if (!needsPolling.value) window.clearInterval(pollTimer)
    }, 4000)
  }
}

watch([loading], () => {
  if (workbench) {
    workbench.stageActions = {
      canRefresh: true,
      refreshing: loading.value,
      onRefresh: () => load(),
      refreshLabel: '刷新状态',
    }
  }
}, { immediate: true })
onMounted(async () => { await load(); startPolling() })
onBeforeUnmount(() => { window.clearInterval(pollTimer); if (workbench) workbench.stageActions = null })
</script>

<template>
  <section class="materials-stage">
    <section class="upload-panel" aria-labelledby="upload-title">
      <div class="upload-copy"><FilePlus2 :size="22" /><div><h3 id="upload-title" class="sfx-panel-title">添加课程材料</h3><p class="sfx-t-caption sfx-t-secondary">支持 PPT、PPTX、PDF、DOC、DOCX；单份最大 50MB。可为每份资料指定教学角色。</p></div></div>
      <input ref="inputRef" class="sr-only" type="file" multiple accept=".ppt,.pptx,.pdf,.doc,.docx" :disabled="uploading" @change="selectFiles" />
      <SfxButton variant="secondary" :disabled="uploading" @click="chooseFiles"><Upload :size="16" /> 选择文件</SfxButton>
      <div v-if="pendingFiles.length" class="pending-list">
        <article v-for="item in pendingFiles" :key="item.id" class="pending-file"><div><strong>{{ item.file.name }}</strong><p class="sfx-t-caption sfx-t-secondary">{{ Math.ceil(item.file.size / 1024) }} KB</p></div><label class="sfx-t-caption">材料角色<select v-model="item.role" class="sfx-select"><option v-for="option in roleOptions" :key="option[0]" :value="option[0]">{{ option[1] }}</option></select></label><SfxButton variant="danger" size="sm" :disabled="uploading" :aria-label="`移除 ${item.file.name}`" @click="removePending(item.id)">移除</SfxButton></article>
      </div>
      <div v-if="uploading" class="upload-status" role="status"><span>正在上传 {{ pendingFiles.length }} 份材料</span><strong>{{ uploadPercent }}%</strong><progress :value="uploadPercent" max="100" /></div>
      <p v-if="uploadError" class="error" role="alert">{{ uploadError }}</p>
      <div class="upload-actions"><SfxButton variant="primary" :disabled="!pendingFiles.length" :loading="uploading" @click="upload">保存并开始解析</SfxButton></div>
    </section>

    <SfxError v-if="!loading && error" :description="error" @retry="load" />
    <template v-else>
      <div class="materials-head"><h2 class="sfx-t-title3">已上传资料</h2><span class="sfx-t-caption sfx-t-secondary">{{ progressText }}</span></div>
      <p v-if="draftBuildText" class="draft-build-status" :class="`draft-build-${draftBuild?.phase}`" role="status">{{ draftBuildText }}</p>
      <p v-if="loading" class="empty">正在读取资料…</p>
      <div v-else-if="!materials.length" class="empty">还没有课程资料。添加主课件、教材或其他教学材料后，解析会在后台继续执行。</div>
      <div v-else class="materials">
        <article v-for="item in materials" :key="item.material_id" class="material"><div><strong>{{ item.name }}</strong><p class="sfx-t-caption sfx-t-secondary">{{ roleLabel[item.material_role] || item.material_role || '参考材料' }} · {{ item.material_type }}</p></div><span class="status" :class="`status-${item.status}`">{{ statusLabel[item.status] || item.status }}</span><small>当前版本：{{ item.current_version_id || '-' }}</small></article>
      </div>
    </template>
  </section>
</template>

<style scoped>
.materials-stage{padding:0;height:100%;overflow-y:auto}
.upload-panel{margin:var(--space-4) 0;border:1px solid var(--border-strong);border-radius:var(--radius-lg);padding:var(--space-4);display:grid;gap:var(--space-3);background:var(--surface-canvas)}
.upload-copy{display:flex;gap:var(--space-2);color:var(--ink-700)}
.upload-copy h3{margin:0;color:var(--text-primary);font-size:var(--ui-md-size)}
.upload-copy p{margin:var(--space-1) 0 0}
.pending-list,.materials{display:grid;gap:var(--space-2)}
.pending-file,.material{display:grid;grid-template-columns:minmax(180px,1fr) 170px auto;align-items:center;gap:var(--space-3);border:1px solid var(--border-default);border-radius:var(--radius-md);padding:var(--space-3);background:var(--surface-panel)}
.pending-file p,.material p{margin:var(--space-1) 0 0}
.pending-file strong,.material strong{color:var(--text-primary);font-size:var(--ui-md-size)}
.pending-file label{display:grid;gap:var(--space-1);color:var(--text-secondary)}
.upload-status{display:grid;grid-template-columns:1fr auto;gap:var(--space-2);color:var(--text-secondary);font-size:var(--ui-sm-size)}
.upload-status progress{grid-column:1/-1;width:100%;accent-color:var(--ink-700)}
.upload-actions{display:flex;justify-content:flex-end}
.materials-head{display:flex;justify-content:space-between;align-items:baseline;gap:var(--space-3);margin:var(--space-4) 0 var(--space-3)}
.materials-head h2{margin:0;color:var(--text-primary);font-size:var(--title-3-size)}
.draft-build-status{margin:0 0 var(--space-3);padding:var(--space-2) var(--space-3);border:1px solid var(--border-default);border-radius:var(--radius-md);background:var(--surface-cool);color:var(--text-secondary);font-size:var(--ui-sm-size);line-height:1.5}
.draft-build-blocked_by_materials,.draft-build-build_failed{border-color:var(--amber-300);background:var(--amber-50);color:var(--amber-700)}
.material small{justify-self:end;font-family:"JetBrains Mono","Fira Code",Consolas,monospace;font-size:11px}
.status{display:inline-flex;align-items:center;gap:var(--space-1);font-size:var(--ui-sm-size);font-weight:600;color:var(--text-secondary)}
.status::before{content:"◇"}
.status-parsing{color:var(--ink-700)}
.status-parsing::before{content:"◌"}
.status-parsed{color:var(--green-700)}
.status-parsed::before{content:"✓"}
.status-failed{color:var(--red-700)}
.status-failed::before{content:"×"}
.status-uploaded,.status-needs_review{color:var(--amber-700)}
.status-uploaded::before,.status-needs_review::before{content:"◷"}
.empty{padding:var(--space-12) var(--space-5);text-align:center;color:var(--text-muted);font-size:var(--ui-md-size)}
.error{margin:0;color:var(--red-700);font-size:var(--ui-sm-size)}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:720px){.materials-stage{padding:var(--space-3)}.materials-head{align-items:stretch;flex-direction:column}.pending-file,.material{grid-template-columns:1fr}.material small{justify-self:start}.upload-actions{justify-content:stretch}.upload-actions :deep(.sfx-btn){width:100%}}
</style>
