<script setup>
import { computed, onBeforeUnmount, onMounted, provide, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { BookOpenCheck, FileText, ListTree, MonitorPlay, Plus, RefreshCw, ShieldCheck, Sparkles, Trash2, Video, Wand2, Waypoints } from 'lucide-vue-next'
import { getDraftBuildStatus } from '@/api/course_build.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import CourseBuildAgentPanel from './CourseBuildAgentPanel.vue'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const selectedNode = ref(null)
const agentOpen = ref(false)
const stageActions = ref(null)
const pendingInstruction = ref('')
const pendingNodeId = ref(null)
const batchRun = ref(null)
const agentMessages = ref([])
// 智能体首次智慧备课阶段：parsing_materials / assembling_corpus / submitting_build / building
// 这些阶段下，structure/scripts/mapping 子页面需要提示"智能体首次智慧备课中"
const draftBuildPhase = ref('')
const workbench = reactive({ selectedNode, agentOpen, stageActions, pendingInstruction, pendingNodeId, batchRun, agentMessages, draftBuildPhase })

provide('courseBuildWorkbench', workbench)

// 删除节点二次确认：切换选中节点或步骤时自动重置
const confirmDelete = ref(false)
watch([selectedNode, () => route.path], () => { confirmDelete.value = false })
function requestDelete() {
  if (!stageActions.value?.canDelete) return
  if (!confirmDelete.value) { confirmDelete.value = true; return }
  confirmDelete.value = false
  stageActions.value.onDelete?.()
}
function requestOrganize() {
  if (batchRun.value) return
  stageActions.value?.onOrganize?.()
}

// 轮询首次智慧备课状态：仅在与备课进度相关的子页面共享该状态
let draftBuildPollTimer = null
async function refreshDraftBuildPhase() {
  try {
    const data = await getDraftBuildStatus(courseId.value)
    draftBuildPhase.value = data?.phase || ''
  } catch (error) {
    // 静默失败：状态读取失败不应阻塞页面渲染
    draftBuildPhase.value = ''
  }
}
function startDraftBuildPolling() {
  window.clearInterval(draftBuildPollTimer)
  refreshDraftBuildPhase()
  draftBuildPollTimer = window.setInterval(refreshDraftBuildPhase, 5000)
}
onMounted(startDraftBuildPolling)
onBeforeUnmount(() => { window.clearInterval(draftBuildPollTimer) })
// 切换课程时重置并重新轮询
watch(courseId, () => {
  selectedNode.value = null
  pendingInstruction.value = ''
  pendingNodeId.value = null
  batchRun.value = null
  agentMessages.value = []
  startDraftBuildPolling()
})

const steps = [
  { key: 'materials', label: '课程资料', description: '上传并解析教学材料', icon: FileText },
  { key: 'structure', label: '课程结构', description: '组织目录与知识点', icon: ListTree },
  { key: 'scripts', label: '讲授脚本', description: '完善教学表达', icon: BookOpenCheck },
  { key: 'mapping', label: '教学 PPT 映射', description: '关联教学演示页', icon: MonitorPlay },
  { key: 'media', label: '媒体与数字人', description: '准备课堂媒体', icon: Video },
  { key: 'validate', label: '检查', description: '运行发布前质量门禁', icon: ShieldCheck },
  { key: 'releases', label: '发布', description: '冻结学生可见版本', icon: Waypoints },
]
const activeStep = computed(() => steps.find((step) => route.name === `app-course-build-${step.key}`) ?? steps[0])
</script>

<template>
  <div class="build-workspace">
    <div class="mobile-workbench-tabs" role="tablist" aria-label="课程建设面板">
      <button type="button" :class="{ active: !agentOpen }" @click="agentOpen = false">建设步骤</button>
      <button type="button" :class="{ active: agentOpen }" @click="agentOpen = true">助教智能体</button>
    </div>

    <div class="build-grid" :class="{ 'agent-is-open': agentOpen }">
      <aside class="build-rail">
        <p class="rail-title">课程建设</p>
        <RouterLink
          v-for="(step, index) in steps"
          :key="step.key"
          :to="`/app/course/${courseId}/build/${step.key}`"
          class="build-link"
          :class="{ active: activeStep.key === step.key }"
        >
          <span class="step-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <component :is="step.icon" :size="17" aria-hidden="true" />
          <span class="step-copy"><strong>{{ step.label }}</strong><small>{{ step.description }}</small></span>
        </RouterLink>
        <p class="rail-note">建设中的内容仅对课程成员可见；学生端只读取已发布的冻结版本。</p>
      </aside>

      <section class="build-stage" aria-live="polite">
        <header class="stage-context">
          <div>
            <p class="eyebrow">STEP {{ String(steps.findIndex((step) => step.key === activeStep.key) + 1).padStart(2, '0') }} · {{ activeStep.key.toUpperCase() }}</p>
            <h1>{{ activeStep.label }}</h1>
            <p>{{ activeStep.description }}</p>
          </div>
          <div class="stage-context-actions">
            <template v-if="stageActions">
              <SfxButton v-if="stageActions.canOrganize !== undefined" variant="secondary" size="sm" :disabled="Boolean(batchRun)" :loading="stageActions.organizing || Boolean(batchRun)" @click="requestOrganize">
                <Wand2 :size="16" /> {{ stageActions.organizeLabel || '智能体一键整理' }}
              </SfxButton>
              <SfxButton v-if="stageActions.canAdd !== undefined" size="sm" :disabled="!stageActions.canAdd" @click="stageActions.onAdd">
                <Plus :size="16" /> {{ stageActions.addLabel || '新增节点' }}
              </SfxButton>
              <SfxButton v-if="stageActions.canDelete !== undefined" variant="danger" size="sm" :disabled="!stageActions.canDelete" :loading="stageActions.deleting" @click="requestDelete">
                <Trash2 :size="16" /> {{ confirmDelete ? '确认删除？' : '删除节点' }}
              </SfxButton>
              <SfxButton v-if="stageActions.canRefresh !== undefined" variant="secondary" size="sm" :disabled="!stageActions.canRefresh" :loading="stageActions.refreshing" @click="stageActions.onRefresh">
                <RefreshCw :size="16" /> {{ stageActions.refreshLabel || '刷新状态' }}
              </SfxButton>
            </template>
            <SfxButton class="agent-trigger" variant="secondary" size="sm" :disabled="Boolean(batchRun)" @click="agentOpen = true"><Sparkles :size="17" /> 打开助教智能体</SfxButton>
          </div>
        </header>
        <div class="stage-body">
          <router-view v-slot="{ Component, route }">
            <Transition name="sfx-page" mode="out-in">
              <component :is="Component" :key="route.path" />
            </Transition>
          </router-view>
        </div>
      </section>

      <CourseBuildAgentPanel :course-id="courseId" :selected-node="selectedNode" @close="agentOpen = false" />
    </div>
  </div>
</template>

<style scoped>
.build-workspace{display:flex;flex-direction:column;flex:1;min-height:0;width:min(100%,1600px);margin:0 auto;padding:var(--space-3) var(--space-5) var(--space-4);box-sizing:border-box;overflow:hidden}.build-grid{display:grid;grid-template-columns:236px minmax(0,1fr) 440px;grid-template-rows:minmax(0,1fr);flex:1;min-height:0;border:1px solid var(--border-default);border-radius:var(--radius-xl);background:var(--surface-panel);overflow:hidden}.build-rail{display:grid;align-content:start;min-height:0;height:100%;padding:var(--space-4) var(--space-2);background:var(--surface-soft);border-right:1px solid var(--border-default);overflow-y:auto}.rail-title{margin:0;padding:0 var(--space-3) var(--space-3);font-size:var(--caption-size);font-weight:650;letter-spacing:.08em;color:var(--text-muted)}.build-link{position:relative;display:grid;grid-template-columns:30px 18px minmax(0,1fr);gap:var(--space-2);align-items:center;min-height:52px;padding:var(--space-2) var(--space-3);color:var(--text-secondary);text-decoration:none;border-radius:var(--radius-md)}.build-link:hover{background:var(--surface-panel);color:var(--ink-900)}.build-link.active{background:var(--ink-100);color:var(--ink-900)}.build-link.active::before{position:absolute;left:-8px;top:10px;bottom:10px;width:3px;background:var(--ink-700);content:""}.step-index{font-family:"JetBrains Mono","Fira Code",Consolas,monospace;font-size:11px;color:var(--text-muted)}.step-copy{display:grid;gap:2px}.step-copy strong{font-size:var(--ui-md-size);font-weight:600}.step-copy small{font-size:11px;line-height:15px;color:var(--text-muted)}.rail-note{margin:var(--space-5) var(--space-3) 0;padding-top:var(--space-4);border-top:1px solid var(--border-default);font-size:var(--caption-size);line-height:1.55;color:var(--text-muted)}.build-stage{min-width:0;min-height:0;align-self:stretch;display:flex;flex-direction:column;padding:var(--space-5);background:var(--surface-page);overflow:hidden}.stage-context{display:flex;justify-content:space-between;gap:var(--space-4);align-items:flex-start;margin-bottom:var(--space-4);flex-shrink:0}.stage-body{flex:1;min-height:0;overflow:hidden}.eyebrow{margin:0 0 var(--space-1);font-size:var(--caption-size);font-weight:650;letter-spacing:.08em;color:var(--ink-500)}h1{margin:0;color:var(--text-primary);font-size:var(--title-2-size);line-height:var(--title-2-line);font-weight:var(--title-2-weight)}.stage-context p:not(.eyebrow){margin:var(--space-1) 0 0;color:var(--text-secondary);font-size:var(--ui-md-size);line-height:1.5}.stage-context-actions{display:flex;align-items:center;gap:var(--space-2);flex-shrink:0}.agent-trigger{display:none}.mobile-workbench-tabs{display:none}
@media(max-width:1250px){.build-grid{grid-template-columns:220px minmax(0,1fr)}.build-grid :deep(.course-build-agent){display:none}.agent-trigger{display:inline-flex}.build-grid.agent-is-open{grid-template-columns:220px minmax(0,1fr)}.build-grid.agent-is-open .build-stage,.build-grid.agent-is-open .build-rail{display:none}.build-grid.agent-is-open :deep(.course-build-agent){display:flex;grid-column:1/-1}}
@media(max-width:760px){.build-workspace{padding:var(--space-2) 0 0;overflow:visible}.build-grid{display:block;flex:none;border-width:1px 0 0;border-radius:0;overflow:visible}.build-rail{display:flex;gap:2px;overflow-x:auto;min-height:0;height:auto;padding:var(--space-2);border:0;border-bottom:1px solid var(--border-default)}.rail-title,.rail-note,.step-index,.step-copy small{display:none}.build-link{display:flex;min-height:40px;white-space:nowrap;padding:0 var(--space-2)}.build-link.active::before{left:8px;right:8px;top:auto;bottom:0;width:auto;height:2px}.build-stage{padding:var(--space-4) var(--space-3);height:auto;overflow:visible}.stage-body{flex:none;overflow:visible}.stage-context{margin-bottom:var(--space-3)}.agent-trigger{display:none}.mobile-workbench-tabs{display:flex;gap:var(--space-1);padding:var(--space-2) var(--space-3);background:var(--surface-panel);border-bottom:1px solid var(--border-default)}.mobile-workbench-tabs button{height:32px;padding:0 var(--space-3);border:0;border-radius:var(--radius-sm);background:transparent;color:var(--text-secondary);font:inherit;font-size:var(--ui-sm-size);cursor:pointer}.mobile-workbench-tabs button.active{background:var(--ink-100);color:var(--ink-900)}.build-grid.agent-is-open .build-stage,.build-grid.agent-is-open .build-rail{display:none}.build-grid.agent-is-open :deep(.course-build-agent){display:flex}}
</style>
