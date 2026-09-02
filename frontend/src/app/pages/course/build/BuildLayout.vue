<script setup>
import { computed, onBeforeUnmount, onMounted, provide, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { BookOpenCheck, ChevronDown, ChevronLeft, ChevronRight, FileText, ListTree, MonitorPlay, Network, Plus, RefreshCw, ShieldCheck, Sparkles, Trash2, Video, Wand2, Waypoints } from 'lucide-vue-next'
import { getDraftBuildStatus } from '@/api/course_build.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import CourseBuildAgentPanel from './CourseBuildAgentPanel.vue'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const selectedNode = ref(null)
// 助教智能体默认展开（2026-08-20 需求）：进入建设布局即以挤压式面板呈现；
// 但知识工作区五个小页面（/build/knowledge/*）默认收起（2026-09-02 需求）：
// 直接以 URL 进入知识区时收起；点击侧栏「知识」步骤按钮则自动展开（见 onStepClick）。
const isKnowledgeRoute = () => route.path.includes('/build/knowledge')
const agentOpen = ref(!isKnowledgeRoute())

// 点击建设步骤按钮：进入知识区时自动展开助教智能体（知识审核常需对照
// 图谱/原文依据，免去再点一次工具栏）；其余步骤保持用户当前展开状态。
function onStepClick(step) {
  if (step.key === 'knowledge') agentOpen.value = true
}

// 建设导航栏收起状态（与学习页 LearningTrack 行为一致：用户手动选择后按设备记忆）
const RAIL_STORAGE_KEY = 'sfx:rail:build'
const railCollapsed = ref(false)
try {
  const saved = localStorage.getItem(RAIL_STORAGE_KEY)
  if (saved === '1' || saved === '0') railCollapsed.value = saved === '1'
} catch { /* localStorage 不可用时保持默认 */ }
watch(railCollapsed, (value) => {
  try { localStorage.setItem(RAIL_STORAGE_KEY, value ? '1' : '0') } catch { /* ignore */ }
})
const stageActions = ref(null)
const pendingInstruction = ref('')
const pendingNodeId = ref(null)
const pendingAgentAction = ref(null)
const batchRun = ref(null)
const agentMessages = ref([])
// 智能体首次智慧备课阶段：parsing_materials / assembling_corpus / submitting_build / building
// 这些阶段下，structure/scripts/mapping 子页面需要提示"智能体首次智慧备课中"
const draftBuildPhase = ref('')
const workbench = reactive({ selectedNode, agentOpen, stageActions, pendingInstruction, pendingNodeId, pendingAgentAction, batchRun, agentMessages, draftBuildPhase })

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
  pendingAgentAction.value = null
  batchRun.value = null
  agentMessages.value = []
  startDraftBuildPolling()
})

const steps = computed(() => [
  { key: 'materials', label: '课程资料', description: '上传并解析教学材料', icon: FileText, to: `/app/course/${courseId.value}/build/materials` },
  { key: 'structure', label: '课程结构', description: '组织目录与教学顺序', icon: ListTree, to: `/app/course/${courseId.value}/build/structure` },
  {
    key: 'knowledge',
    label: '知识',
    description: '审核知识结构与原文依据',
    icon: Network,
    to: `/app/course/${courseId.value}/build/knowledge/graph`,
    // 知识工作区已并入建设布局（/build/knowledge/* 五个子页面）；
    // 侧栏内展开子页面直达菜单，避免教师为到达"知识包审批"等高频页多跳一次。
    children: [
      { key: 'graph', label: '结构视图', to: `/app/course/${courseId.value}/build/knowledge/graph`, matchName: 'app-course-build-knowledge' },
      { key: 'evidence', label: '原文引用', to: `/app/course/${courseId.value}/build/knowledge/evidence`, matchName: 'app-course-build-knowledge-evidence' },
      { key: 'reviews', label: '知识包审批', to: `/app/course/${courseId.value}/build/knowledge/reviews`, matchName: 'app-course-build-knowledge-reviews' },
      { key: 'candidates', label: '节点审核', to: `/app/course/${courseId.value}/build/knowledge/candidates`, matchName: 'app-course-build-knowledge-candidates' },
      { key: 'snapshots', label: '版本记录', to: `/app/course/${courseId.value}/build/knowledge/snapshots`, matchName: 'app-course-build-knowledge-snapshots' },
    ],
  },
  { key: 'scripts', label: '讲授脚本', description: '完善教学表达', icon: BookOpenCheck, to: `/app/course/${courseId.value}/build/scripts` },
  { key: 'mapping', label: '教学 PPT 映射', description: '关联教学演示页', icon: MonitorPlay, to: `/app/course/${courseId.value}/build/mapping` },
  { key: 'media', label: '媒体与数字人', description: '准备课堂媒体', icon: Video, to: `/app/course/${courseId.value}/build/media` },
  { key: 'validate', label: '检查', description: '查看正式发布前的问题', icon: ShieldCheck, to: `/app/course/${courseId.value}/build/validate` },
  { key: 'releases', label: '正式发布', description: '让学生看到这版课程内容', icon: Waypoints, to: `/app/course/${courseId.value}/build/releases` },
])
const activeStep = computed(() => {
  const step = steps.value.find((step) => route.name === `app-course-build-${step.key}`)
  if (step) return step
  // 知识工作区子页面（evidence/reviews/candidates/snapshots）归入知识步骤
  if (String(route.name || '').startsWith('app-course-build-knowledge')) {
    return steps.value.find((step) => step.key === 'knowledge')
  }
  return steps.value[0]
})
// 知识步骤子菜单（知识工作区页面直达）展开状态；
// 初始值：已处于知识工作区子页面时默认展开，保证选中标识可见
const knowledgeOpen = ref(String(route.name || '').startsWith('app-course-build-knowledge'))
</script>

<template>
  <div class="build-workspace">
    <div class="mobile-workbench-tabs" role="tablist" aria-label="课程建设面板">
      <SfxButton variant="tertiary" size="sm" :class="{ active: !agentOpen }" @click="agentOpen = false">建设步骤</SfxButton>
      <SfxButton variant="tertiary" size="sm" :class="{ active: agentOpen }" @click="agentOpen = true">助教智能体</SfxButton>
    </div>

    <div class="build-grid" :class="{ 'rail-collapsed': railCollapsed }">
      <aside class="build-rail">
        <div class="rail-scroll">
        <p class="rail-title">课程建设</p>
        <div
          v-for="(step, index) in steps"
          :key="step.key"
          class="build-link-wrap"
          :class="{ 'has-children': Boolean(step.children) }"
        >
          <RouterLink
            :to="step.to"
            class="build-link"
            :class="{ active: activeStep.key === step.key }"
            :title="railCollapsed ? step.label : ''"
            @click="onStepClick(step)"
          >
            <span class="step-index">{{ String(index + 1).padStart(2, '0') }}</span>
            <component :is="step.icon" :size="17" aria-hidden="true" />
            <span class="step-copy"><strong>{{ step.label }}</strong><small>{{ step.description }}</small></span>
          </RouterLink>
          <!-- 知识步骤子菜单开关：点击展开知识工作区页面直达列表（不触发导航）；
               单图标 + CSS 旋转，避免切换图标造成的视觉位移 -->
          <button
            v-if="step.children && !railCollapsed"
            type="button"
            class="build-sub-toggle"
            :class="{ open: knowledgeOpen }"
            :aria-expanded="knowledgeOpen"
            :aria-label="knowledgeOpen ? '收起知识工作区页面' : '展开知识工作区页面'"
            @click="knowledgeOpen = !knowledgeOpen"
          >
            <ChevronDown :size="14" aria-hidden="true" />
          </button>
          <!-- 知识工作区页面直达：rail 内展开，grid-rows 过渡动画 -->
          <div v-if="step.children && !railCollapsed" class="build-sub" :class="{ open: knowledgeOpen }" role="menu" aria-label="知识工作区页面">
            <div class="build-sub-inner">
              <RouterLink
                v-for="child in step.children"
                :key="child.key"
                :to="child.to"
                class="build-sub-link"
                :class="{ active: route.name === child.matchName }"
                role="menuitem"
                :aria-current="route.name === child.matchName ? 'page' : undefined"
                :tabindex="knowledgeOpen ? undefined : -1"
              >
                {{ child.label }}
              </RouterLink>
            </div>
          </div>
        </div>
        <p class="rail-note">建设中的内容仅对课程成员可见；学生端只读取正式发布的课程版本。</p>
        </div>
      </aside>
      <button
        type="button"
        class="rail-toggle"
        :aria-label="railCollapsed ? '展开建设导航' : '收起建设导航'"
        :title="railCollapsed ? '展开' : '收起'"
        @click="railCollapsed = !railCollapsed"
      >
        <ChevronLeft v-if="!railCollapsed" :size="16" />
        <ChevronRight v-else :size="16" />
      </button>

      <section class="build-stage" aria-live="polite">
        <header class="stage-context">
          <div>
            <p class="eyebrow">STEP {{ String(steps.findIndex((step) => step.key === activeStep.key) + 1).padStart(2, '0') }} · {{ activeStep.key.toUpperCase() }}</p>
            <h1>{{ activeStep.label }}</h1>
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
          </div>
        </header>
        <div class="stage-body">
          <router-view v-slot="{ Component, route }">
            <Transition name="sfx-page" mode="out-in">
              <component :is="Component" :key="route.path" />
            </Transition>
          </router-view>
        </div>

        <!-- 助教智能体折叠态：舞台右上角工具球（浮动入口） -->
        <Transition name="agent-fab">
          <button v-if="!agentOpen" type="button" class="agent-fab" aria-label="打开助教智能体" title="打开助教智能体" @click="agentOpen = true">
            <Sparkles :size="20" aria-hidden="true" />
          </button>
        </Transition>
      </section>

      <!-- 助教智能体展开态：作为布局列直接挤压舞台区（宽度过渡动画） -->
      <div class="agent-dock" :class="{ open: agentOpen }">
        <CourseBuildAgentPanel :course-id="courseId" :selected-node="selectedNode" @close="agentOpen = false" />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 外层：与 .sfx-learn 一致的裸 flex 列布局，不再卡片化 */
.build-workspace{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}
.build-grid{flex:1;min-height:0;display:flex;overflow:hidden;position:relative}
/* design.md §12.5：aside 不直接 overflow-y:auto（避免 overflow-x 隐式 auto 裁掉
   知识步骤的伸出式子菜单），滚动职责由内部 .rail-scroll 承担 */
.build-rail{display:flex;flex-direction:column;min-height:0;height:100%;width:var(--rail-width);flex-shrink:0;background:var(--surface-soft);border-right:1px solid var(--border-default);transition:width var(--duration-normal) var(--ease-out)}
/* scrollbar-gutter:stable——知识子菜单展开后 rail 内容变高出现滚动条，
   预留滚动条空间避免子菜单开关按钮被横向挤压位移 */
.rail-scroll{flex:1;min-height:0;overflow-y:auto;overflow-x:visible;scrollbar-gutter:stable;display:grid;align-content:start;padding:var(--space-4) var(--space-2)}
.rail-toggle{position:absolute;top:var(--space-3);left:calc(var(--rail-width) - 13px);width:26px;height:26px;border-radius:var(--radius-full);background:var(--surface-panel);border:1px solid var(--border-default);color:var(--text-secondary);display:inline-flex;align-items:center;justify-content:center;cursor:pointer;z-index:30;transition:left var(--duration-normal) var(--ease-out)}
.rail-toggle:hover{color:var(--ink-700);border-color:var(--border-strong)}
.rail-title{margin:0;padding:0 var(--space-3) var(--space-3);font-size:var(--caption-size);font-weight:650;letter-spacing:.08em;color:var(--text-muted)}
.build-link{position:relative;display:grid;grid-template-columns:30px 18px minmax(0,1fr);gap:var(--space-2);align-items:center;min-height:52px;padding:var(--space-2) var(--space-3);color:var(--text-secondary);text-decoration:none;border-radius:var(--radius-md)}
.build-link:hover{background:var(--surface-panel);color:var(--ink-900)}
.build-link.active{background:var(--ink-100);color:var(--ink-900)}
.build-link.active::before{position:absolute;left:0;top:var(--space-2);bottom:var(--space-2);width:3px;background:var(--ink-900);content:"";border-radius:var(--radius-full)}
.step-index{font-family:"JetBrains Mono","Fira Code",Consolas,monospace;font-size:var(--caption-size);color:var(--text-muted)}
.step-copy{display:grid;gap:2px}
.step-copy strong{font-size:var(--ui-md-size);font-weight:600}
.step-copy small{font-size:var(--caption-size);line-height:15px;color:var(--text-muted)}
.rail-note{margin:var(--space-5) var(--space-3) 0;padding-top:var(--space-4);border-top:1px solid var(--border-default);font-size:var(--caption-size);line-height:1.55;color:var(--text-muted)}
/* 知识步骤包一层 wrap 以承载子菜单开关与展开列表 */
.build-link-wrap{position:relative}
/* 有子菜单的步骤：右侧留出开关按钮热区 */
.build-link-wrap.has-children .build-link{padding-right:30px}
/* 子菜单开关（绝对定位在 link 右侧，点击只展开不导航）；
   top 固定为链接高度一半（52/2），不能用 50%——wrap 展开子菜单后整体高度
   变大，会把开关推离链接中心；图标用旋转过渡，位置恒定 */
.build-sub-toggle{position:absolute;right:3px;top:26px;z-index:2;width:24px;height:24px;border:0;border-radius:var(--radius-sm);background:transparent;color:var(--text-muted);display:inline-flex;align-items:center;justify-content:center;cursor:pointer}
.build-sub-toggle:hover{background:var(--border-subtle);color:var(--ink-700)}
.build-sub-toggle svg{transition:transform var(--duration-normal) var(--ease-out)}
.build-sub-toggle.open svg{transform:rotate(180deg)}
/* 知识工作区页面直达列表：grid-rows 0fr→1fr 过渡实现展开/收起动画 */
.build-sub{display:grid;grid-template-rows:0fr;transition:grid-template-rows var(--duration-normal) var(--ease-out)}
.build-sub.open{grid-template-rows:1fr}
.build-sub-inner{overflow:hidden;min-height:0;display:grid;gap:2px;margin:2px 0 var(--space-1);padding-left:26px}
.build-sub-link{position:relative;display:flex;align-items:center;min-height:32px;padding:0 var(--space-2);border-radius:var(--radius-sm);color:var(--text-secondary);font-size:var(--ui-sm-size);text-decoration:none;white-space:nowrap}
.build-sub-link:hover{background:var(--ink-100);color:var(--ink-900)}
.build-sub-link.active{background:var(--ink-100);color:var(--ink-900);font-weight:600}
/* 选中标识：左侧状态线，与 .build-link.active::before 同视觉语言 */
.build-sub-link.active::before{position:absolute;left:-10px;top:7px;bottom:7px;width:3px;background:var(--ink-900);content:"";border-radius:var(--radius-full)}
.build-stage{flex:1;min-width:0;min-height:0;display:flex;flex-direction:column;padding:var(--space-6);background:var(--surface-panel);overflow:hidden;position:relative}
/* 右侧预留 52px 给助教智能体工具球，避免与标题区操作按钮重叠 */
.stage-context{display:flex;justify-content:space-between;gap:var(--space-4);align-items:flex-start;margin-bottom:var(--space-6);flex-shrink:0;flex-wrap:wrap;padding-right:52px}
.stage-context>div:first-child{min-width:0;flex:1 1 220px}
.stage-body{flex:1;min-height:0;overflow:hidden}
.eyebrow{margin:0 0 var(--space-1);font-size:var(--caption-size);font-weight:650;letter-spacing:.08em;color:var(--ink-500)}
h1{margin:0;color:var(--text-primary);font-size:var(--title-2-size);line-height:var(--title-2-line);font-weight:var(--title-2-weight)}
.stage-context-actions{display:flex;align-items:center;gap:var(--space-2);flex:0 1 auto;flex-wrap:wrap;justify-content:flex-end}
.mobile-workbench-tabs{display:none}
/* 助教智能体折叠态：舞台右上角工具球（浮动入口） */
.agent-fab{position:absolute;top:var(--space-3);right:var(--space-3);z-index:40;width:46px;height:46px;border:1px solid var(--border-default);border-radius:var(--radius-full);background:var(--surface-panel);color:var(--ink-700);display:inline-flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:var(--shadow-md);transition:color var(--duration-fast) var(--ease-out),box-shadow var(--duration-fast) var(--ease-out)}
.agent-fab:hover{color:var(--ink-900);box-shadow:var(--shadow-md),0 0 0 4px var(--ink-100)}
/* 助教智能体展开态：布局列挤压舞台区；dock 宽度 0→460 过渡，
   内部面板定宽 460 避免内容在动画期间被压扁 */
.agent-dock{width:0;height:100%;flex-shrink:0;overflow:hidden;transition:width var(--duration-normal) var(--ease-out)}
.agent-dock.open{width:var(--agent-panel-width)}
.agent-dock :deep(.course-build-agent){width:var(--agent-panel-width);min-width:var(--agent-panel-width);height:100%}
/* 收起时面板不可聚焦，避免 Tab 进入隐藏区域 */
.agent-dock:not(.open) :deep(.course-build-agent){visibility:hidden}
/* 工具球淡入淡出过渡 */
.agent-fab-enter-active,.agent-fab-leave-active{transition:opacity var(--duration-normal) var(--ease-out),transform var(--duration-normal) var(--ease-out);transform-origin:top right}
.agent-fab-enter-from,.agent-fab-leave-to{opacity:0;transform:scale(.5)}
/* 收缩态：rail 宽度收到 --rail-width-collapsed，仅显示图标（参考 SfxLocalRail） */
.build-grid.rail-collapsed .build-rail{width:var(--rail-width-collapsed)}
.build-grid.rail-collapsed .rail-toggle{left:calc(var(--rail-width-collapsed) - 13px)}
.build-grid.rail-collapsed .rail-title,.build-grid.rail-collapsed .rail-note,.build-grid.rail-collapsed .step-index,.build-grid.rail-collapsed .step-copy{display:none}
.build-grid.rail-collapsed .build-link{display:flex;justify-content:center;align-items:center;min-height:44px;padding:var(--space-2)}
.build-grid.rail-collapsed .build-link.active::before{left:0;top:4px;bottom:4px}
@media(max-width:760px){.build-workspace{overflow:visible}.build-grid{flex:none;flex-direction:column;overflow:visible}/* 触屏横向 rail 不提供子菜单展开，点击直接进入知识工作区 */.build-sub,.build-sub-toggle{display:none}.build-rail{min-height:0;height:auto;width:100%;border:0;border-bottom:1px solid var(--border-default);transition:none}.rail-scroll{display:flex;gap:2px;overflow-x:auto;overflow-y:hidden;padding:var(--space-2)}.rail-toggle{display:none}.rail-title,.rail-note,.step-index,.step-copy small{display:none}.build-link{display:flex;min-height:40px;white-space:nowrap;padding:0 var(--space-2)}.build-link.active::before{left:8px;right:8px;top:auto;bottom:0;width:auto;height:2px}.build-stage{padding:var(--space-4) var(--space-3);height:auto;overflow:visible}.stage-body{flex:none;overflow:visible}.stage-context{margin-bottom:var(--space-3);padding-right:52px}.mobile-workbench-tabs{display:flex;gap:var(--space-1);padding:var(--space-2) var(--space-3);background:var(--surface-panel);border-bottom:1px solid var(--border-default)}.mobile-workbench-tabs button{height:32px;padding:0 var(--space-3);border:0;border-radius:var(--radius-sm);background:transparent;color:var(--text-secondary);font:inherit;font-size:var(--ui-sm-size);cursor:pointer}.mobile-workbench-tabs button.active{background:var(--ink-100);color:var(--ink-900)}/* 移动端 dock 全宽出现在舞台下方（高度过渡），面板高度自适应 */.agent-dock{width:100%;height:0;transition:height var(--duration-normal) var(--ease-out)}.agent-dock.open{height:min(70vh,640px)}.agent-dock :deep(.course-build-agent){width:100%;min-width:0;height:100%}}
</style>
