<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { LockKeyhole, Save, Sparkles } from 'lucide-vue-next'
import { getTeachingScripts, lockTeachingScript, updateTeachingScript } from '@/api/course_editor.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const workbench = inject('courseBuildWorkbench', null)
const state = ref('loading')
const error = ref('')
const items = ref([])
const editable = ref(false)
const selectedId = ref('')
const saving = ref('')
const selected = computed(() => items.value.find((item) => item.script_node_id === selectedId.value) ?? null)

function select(item) { selectedId.value = item.script_node_id }
async function load() {
  state.value = 'loading'; error.value = ''
  try {
    const data = await getTeachingScripts(courseId.value)
    items.value = data?.items ?? []
    editable.value = Boolean(data?.editable)
    if (!items.value.some((item) => item.script_node_id === selectedId.value)) selectedId.value = items.value[0]?.script_node_id ?? ''
    state.value = 'ready'
  } catch (caught) { error.value = caught?.message || '讲稿读取失败'; state.value = 'error' }
}
async function save(item) {
  if (!editable.value || item.locked) return
  saving.value = item.script_node_id
  try { await updateTeachingScript(courseId.value, item.script_node_id, { content: item.content, style: item.style }) }
  catch (caught) { error.value = caught?.message || '讲稿保存失败' }
  finally { saving.value = '' }
}
async function lock(item) {
  try { await lockTeachingScript(courseId.value, item.script_node_id); item.locked = true }
  catch (caught) { error.value = caught?.message || '锁定讲稿失败' }
}
function openAgent(customInstruction) {
  if (!workbench) return
  workbench.agentOpen = true
  if (customInstruction) {
    workbench.pendingInstruction = customInstruction
  }
}
function openAgentForNode() {
  const node = selected.value
  const nodeId = node?.outline_node_id || '当前节点'
  openAgent(`请针对讲稿节点「${nodeId}」的内容和风格提出润色建议，使其更符合教学表达规范。`)
}
function refreshAfterProposal() { load() }

watch([editable, items], () => {
  if (workbench) {
    workbench.stageActions = {
      canOrganize: editable.value && items.value.length > 0,
      organizing: false,
      onOrganize: () => openAgentForNode(),
      organizeLabel: '让智能体润色',
    }
  }
}, { immediate: true })
onMounted(() => { load(); window.addEventListener('course-build-proposal-decided', refreshAfterProposal) })
onBeforeUnmount(() => { window.removeEventListener('course-build-proposal-decided', refreshAfterProposal); if (workbench) workbench.stageActions = null })
</script>

<template>
  <section class="scripts-stage">
    <SfxSkeleton v-if="state === 'loading'" :lines="6" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />
    <div v-else-if="!items.length" class="empty-state"><Sparkles :size="22" /><strong>讲授脚本尚未生成</strong><p>先确认课程结构并完成首次智能备课，系统才会生成可审核的讲稿草稿。</p></div>
    <div v-else class="scripts-workbench">
      <div class="script-list" aria-label="讲稿节点列表">
        <button v-for="item in items" :key="item.script_node_id" class="script-row" :class="{ selected: selectedId === item.script_node_id }" type="button" @click="select(item)">
          <span><strong>{{ item.outline_node_id }}</strong><small>{{ item.locked ? '已锁定' : '草稿可编辑' }}</small></span><LockKeyhole v-if="item.locked" :size="15" />
        </button>
      </div>
      <article v-if="selected" class="script-editor">
        <header><div><p>关联目录节点</p><h3>{{ selected.outline_node_id }}</h3></div><SfxBadge :tone="selected.locked ? 'green' : 'amber'">{{ selected.locked ? '已锁定' : '草稿' }}</SfxBadge></header>
        <label>讲授脚本<textarea v-model="selected.content" :disabled="!editable || selected.locked" @blur="save(selected)" /></label>
        <label>讲解风格<input v-model="selected.style" :disabled="!editable || selected.locked" placeholder="例如：面向大一学生，循序解释" @blur="save(selected)" /></label>
        <p v-if="saving === selected.script_node_id" class="saving"><Save :size="14" /> 正在保存讲稿</p>
        <div class="script-actions"><SfxButton v-if="!selected.locked" variant="secondary" size="sm" :disabled="!editable" @click="lock(selected)"><LockKeyhole :size="15" /> 锁定讲稿</SfxButton><SfxButton variant="tertiary" size="sm" @click="openAgentForNode"><Sparkles :size="15" /> 生成调整提案</SfxButton></div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.scripts-stage{display:flex;flex-direction:column;gap:0;padding:0;height:100%;overflow:hidden}
.scripts-workbench{display:grid;grid-template-columns:minmax(220px,.7fr) minmax(360px,1.3fr);gap:var(--space-4);min-height:0;flex:1;overflow:hidden}
.script-list{display:grid;align-content:start;border:1px solid var(--border-default);border-radius:var(--radius-md);overflow-y:auto;min-height:0}
.script-row{display:flex;justify-content:space-between;align-items:center;gap:var(--space-2);min-height:58px;padding:0 var(--space-3);border:0;border-bottom:1px solid var(--border-subtle);background:var(--surface-panel);color:var(--text-primary);text-align:left;cursor:pointer;font:inherit}
.script-row:last-child{border-bottom:0}
.script-row:hover{background:var(--surface-cool)}
.script-row.selected{background:var(--ink-100);box-shadow:inset 3px 0 var(--ink-700)}
.script-row span{display:grid;gap:2px}
.script-row strong{font-family:var(--font-mono);font-size:var(--caption-size);font-weight:500}
.script-row small{font-size:var(--caption-size);color:var(--text-muted)}
.script-editor{display:grid;gap:var(--space-3);padding:var(--space-4);border:1px solid var(--border-default);border-radius:var(--radius-lg);background:var(--surface-canvas);overflow-y:auto;min-height:0}
.script-editor header{display:flex;justify-content:space-between;align-items:flex-start;gap:var(--space-2)}
.script-editor header p{margin:0;color:var(--text-muted);font-size:var(--caption-size)}
.script-editor header h3{margin:var(--space-1) 0 0;color:var(--text-primary);font-family:var(--font-mono);font-size:var(--ui-md-size)}
.script-editor label{display:grid;gap:var(--space-1);color:var(--text-secondary);font-size:var(--ui-sm-size);font-weight:600}
.script-editor textarea,.script-editor input{box-sizing:border-box;width:100%;border:1px solid var(--border-default);border-radius:var(--radius-md);outline:none;background:var(--surface-panel);color:var(--text-primary);font:inherit}
.script-editor textarea{min-height:280px;padding:var(--space-3);font-size:var(--body-md-size);line-height:var(--body-md-line);resize:vertical}
.script-editor input{height:40px;padding:0 var(--space-3);font-size:var(--ui-md-size)}
.script-editor textarea:focus,.script-editor input:focus{border-color:var(--ink-500);box-shadow:0 0 0 2px var(--ink-100)}
.script-editor textarea:disabled,.script-editor input:disabled{background:var(--surface-cool);color:var(--text-secondary)}
.saving{display:flex;align-items:center;gap:var(--space-1);margin:0;color:var(--text-muted);font-size:var(--caption-size)}
.script-actions{display:flex;flex-wrap:wrap;gap:var(--space-2)}
.empty-state{display:grid;justify-items:center;gap:var(--space-2);padding:var(--space-12) var(--space-5);color:var(--text-muted);text-align:center}
.empty-state strong{color:var(--text-primary);font-size:var(--title-3-size)}
.empty-state p{max-width:440px;margin:0;font-size:var(--ui-md-size);line-height:1.6}
@media(max-width:880px){.scripts-workbench{grid-template-columns:1fr;overflow:visible}.script-list{max-height:260px;overflow:auto}}
@media(max-width:560px){.scripts-stage{padding:var(--space-3)}.script-editor{padding:var(--space-3)}.script-actions :deep(.sfx-btn){flex:1}}
</style>
