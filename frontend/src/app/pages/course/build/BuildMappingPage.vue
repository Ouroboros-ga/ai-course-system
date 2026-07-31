<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { generateCoursePpt, getPptMappingState, optimizePptMapping, updatePptMapping, uploadExistingPpt } from '@/api/course_editor.js'
import { useRoute } from 'vue-router'
import { Sparkles } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'
import { apiErrorMessage } from '@/utils/apiErrorMessage.js'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const workbench = inject('courseBuildWorkbench', null)
const state = ref(null)
const loading = ref(true)
const optimizing = ref(false)
const inputRef = ref(null)
const message = ref('')
const prepBatchRunning = computed(() => Boolean(workbench?.batchRun))

// 智能体首次智慧备课进行中：解析材料 / 汇总语料 / 提交任务 / 构建中
const FIRST_PREP_PHASES = new Set(['parsing_materials', 'assembling_corpus', 'submitting_build', 'building'])
const isFirstPrepInProgress = computed(() => FIRST_PREP_PHASES.has(workbench?.draftBuildPhase))

async function load() {
  loading.value = true
  try { state.value = await getPptMappingState(courseId.value) } catch (error) { message.value = error?.message || '映射状态读取失败' } finally { loading.value = false }
}
async function onUpload(event) {
  const file = event.target.files?.[0]
  if (!file) return
  message.value = '正在上传并创建解析任务…'
  try { await uploadExistingPpt(courseId.value, file); message.value = '上传成功，解析任务已进入任务中心'; await load() } catch (error) { message.value = error?.message || '上传失败' }
  event.target.value = ''
}
async function onGenerate() {
  message.value = '正在请求 AI PPT 生成…'
  try { await generateCoursePpt(courseId.value); message.value = 'AI PPT 已生成并进入统一解析链'; await load() } catch (error) { message.value = error?.message || 'AI PPT 暂不可用' }
}
async function onOptimize() {
  if (optimizing.value || prepBatchRunning.value) return
  if (isFirstPrepInProgress.value) return reportOptimizeUnavailable('首次智能备课仍在进行，PPT 映射将在课程草稿生成后开放优化。')
  if (!state.value?.has_ppt) return reportOptimizeUnavailable('尚未上传并完成解析的 PPT，暂无可优化的映射。')
  optimizing.value = true; message.value = ''
  const agentMessage = {
    role: 'agent',
    running: true,
    reason: '正在基于 PPT OCR 文本优化全部未锁定映射，请勿发起其他智能优化。',
    changed: [],
  }
  if (workbench) {
    workbench.agentOpen = true
    workbench.batchRun = { action: 'optimize_ppt_mapping', startedAt: Date.now() }
    workbench.agentMessages.push(agentMessage)
  }
  try {
    const result = await optimizePptMapping(courseId.value)
    message.value = `优化完成：共更新 ${result.updated_count} 条映射`
    await load()
    Object.assign(agentMessage, {
      running: false,
      reason: 'PPT 映射优化已完成并直接应用。',
      changed: [`已更新 ${result.updated_count || 0} 条映射`],
    })
  } catch (error) {
    message.value = apiErrorMessage(error, 'PPT 映射优化失败')
    Object.assign(agentMessage, { running: false, error: true, reason: message.value })
  } finally {
    if (workbench) workbench.batchRun = null
    optimizing.value = false
  }
}
function reportOptimizeUnavailable(reason) {
  message.value = reason
  if (!workbench) return
  workbench.agentOpen = true
  workbench.agentMessages.push({ role: 'agent', error: true, reason })
}
async function saveMapping(node) {
  try { await updatePptMapping(courseId.value, node.outline_node_id, { page_range: node.page_range, confidence: node.confidence }) } catch (error) { message.value = error?.message || '映射保存失败' }
}

// 通过 stageActions 把"一键优化映射"暴露给 BuildLayout 的 stage-context 工具栏
const canOrganize = computed(() => Boolean(state.value?.has_ppt) && !optimizing.value && !prepBatchRunning.value)
watch([canOrganize, optimizing, prepBatchRunning], () => {
  if (workbench) {
    workbench.stageActions = {
      canOrganize: canOrganize.value,
      organizing: optimizing.value,
      onOrganize: onOptimize,
      organizeLabel: '一键优化映射',
    }
  }
}, { immediate: true })

onMounted(load)
onBeforeUnmount(() => { if (workbench) workbench.stageActions = null })
</script>

<template>
  <section class="stage">
    <div v-if="loading" class="empty">正在读取映射状态…</div>
    <div v-else-if="isFirstPrepInProgress && !state?.has_ppt" class="first-prep-pending" role="status" aria-live="polite">
      <div class="first-prep-icon" aria-hidden="true"><Sparkles :size="26" :stroke-width="1.8" /></div>
      <h3>智能体首次智慧备课中</h3>
      <p>助教智能体正在解析课程材料，并整理课程结构与讲授脚本。完成首次备课后，PPT 映射才能基于已确认的节点生成。</p>
      <div class="first-prep-progress" aria-hidden="true"><span></span><span></span><span></span></div>
    </div>
    <div v-else-if="!state?.has_ppt" class="frozen">
      <h2>当前课程尚无可映射的 PPT 文件</h2>
      <p>PDF、DOCX 和 DOC 的页码仍可用于原文引用，但不会自动成为教学 PPT 映射。</p>
      <input ref="inputRef" hidden type="file" accept=".ppt,.pptx" @change="onUpload" />
      <div class="actions"><SfxButton variant="primary" size="sm" @click="inputRef?.click()">上传现有 PPT</SfxButton><SfxButton variant="tertiary" size="sm" :disabled="!state?.actions?.generate_ai" @click="onGenerate">AI 智慧生成 PPT</SfxButton></div>
      <small>根据已经确认的课程结构和讲授脚本生成</small>
    </div>
    <div v-else class="ready">
      <h2>已发现 PPT 文件</h2><p>可编辑课程节点对应的幻灯片页码。</p>
      <div class="actions"><SfxButton variant="tertiary" size="sm" :disabled="optimizing || prepBatchRunning" @click="onOptimize"><Sparkles :size="14" /> 一键优化映射</SfxButton></div>
      <div class="mapping-list"><label v-for="node in state.nodes" :key="node.outline_node_id"><span>{{ node.display_label || node.title }}</span><input v-model="node.page_range" placeholder="页码，例如 1-3" @blur="saveMapping(node)" /></label></div>
    </div>
    <p v-if="message" class="message">{{ message }}</p>
  </section>
</template>

<style scoped>
.stage{padding:0;height:100%;overflow-y:auto}
.frozen,.ready{border:1px dashed var(--border-strong);border-radius:var(--radius-lg);padding:var(--space-8) var(--space-6);text-align:center;background:var(--surface-cool);color:var(--text-secondary)}
.frozen h2,.ready h2{color:var(--text-primary)}
.actions{display:flex;justify-content:center;gap:var(--space-2);margin:var(--space-6) 0 var(--space-2)}
.frozen small{color:var(--text-muted)}
.empty{text-align:center;padding:var(--space-12);color:var(--text-muted)}
.mapping-list{display:grid;gap:var(--space-2);text-align:left;margin:var(--space-6) auto;max-width:720px}
.mapping-list label{display:flex;align-items:center;gap:var(--space-3);padding:var(--space-2);background:var(--surface-panel);border:1px solid var(--border-default);border-radius:var(--radius-sm)}
.mapping-list span{flex:1}
.mapping-list input{width:150px;padding:var(--space-1);border:1px solid var(--border-strong);border-radius:var(--radius-sm)}
.message{margin-top:var(--space-4);color:var(--ink-700)}
.first-prep-pending{display:grid;justify-items:center;gap:var(--space-3);padding:var(--space-12) var(--space-5);color:var(--text-secondary);text-align:center}
.first-prep-pending h3{margin:0;color:var(--text-primary);font-size:var(--title-3-size);font-weight:var(--title-3-weight)}
.first-prep-pending p{max-width:440px;margin:0;font-size:var(--ui-md-size);line-height:1.6}
.first-prep-icon{width:56px;height:56px;border-radius:var(--radius-full);background:var(--ink-100);color:var(--ink-700);display:flex;align-items:center;justify-content:center;animation:first-prep-pulse 1.6s ease-in-out infinite}
.first-prep-progress{display:flex;gap:var(--space-2)}
.first-prep-progress span{width:8px;height:8px;border-radius:var(--radius-full);background:var(--ink-500);opacity:.4;animation:first-prep-bounce 1.2s ease-in-out infinite}
.first-prep-progress span:nth-child(2){animation-delay:.15s}
.first-prep-progress span:nth-child(3){animation-delay:.3s}
@keyframes first-prep-pulse{0%,100%{transform:scale(1);box-shadow:0 0 0 0 rgba(var(--ink-700-rgb, 60, 90, 160),.25)}50%{transform:scale(1.06);box-shadow:0 0 0 10px rgba(var(--ink-700-rgb, 60, 90, 160),0)}}
@keyframes first-prep-bounce{0%,100%{transform:translateY(0);opacity:.4}50%{transform:translateY(-6px);opacity:1}}
</style>
