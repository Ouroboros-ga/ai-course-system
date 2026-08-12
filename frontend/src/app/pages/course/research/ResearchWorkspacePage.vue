<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import {
  AlertTriangle,
  BarChart3,
  BookOpen,
  BrainCircuit,
  Check,
  Clipboard,
  Code2,
  ExternalLink,
  FilePenLine,
  GitBranch,
  LibraryBig,
  ListTodo,
  Network,
  Search,
  ShieldCheck,
  StickyNote,
} from 'lucide-vue-next'
import {
  getResearchAgentCapabilities,
  getResearchWorkspace,
  runResearchHarness,
} from '@/api/research_agent.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import ResearchMemoryPanel from './components/ResearchMemoryPanel.vue'
import ResearchNotepadPanel from './components/ResearchNotepadPanel.vue'
import ResearchScopePanel from './components/ResearchScopePanel.vue'
import ResearchTodoPanel from './components/ResearchTodoPanel.vue'

const { courseId } = inject('courseContext')

const query = ref('')
const loading = ref(false)
const capabilityLoading = ref(true)
const workspaceLoading = ref(true)
const error = ref('')
const notice = ref('')
const result = ref(null)
const manifest = ref(null)
const workspace = ref(null)
const selectedId = ref('')
const activeView = ref('search')
const harnessMeta = ref(null)
const memoryResults = ref([])
const memoryRetrievalMode = ref('')

const fallbackStages = [
  { key: 'research_harness', label: '科研编排', status: 'available', icon: BrainCircuit },
  { key: 'literature_search', label: '文献检索', status: 'available', icon: LibraryBig },
  { key: 'trend_analysis', label: '趋势分析', status: 'research_preview', icon: BarChart3 },
  { key: 'evidence_synthesis', label: '证据综合', status: 'research_preview', icon: Network },
  { key: 'writing_assist', label: '学术写作', status: 'research_preview', icon: FilePenLine },
  { key: 'code_reproduction', label: '代码复现', status: 'research_preview', icon: Code2 },
]

const stageIcon = {
  research_harness: BrainCircuit,
  literature_search: LibraryBig,
  trend_analysis: BarChart3,
  evidence_synthesis: Network,
  writing_assist: FilePenLine,
  code_reproduction: Code2,
}

const workbenchViews = [
  { key: 'search', label: '论文检索', icon: Search },
  { key: 'todos', label: '研究任务', icon: ListTodo },
  { key: 'notepad', label: '研究笔记', icon: StickyNote },
  { key: 'memory', label: '研究记忆', icon: BrainCircuit },
  { key: 'scopes', label: '子任务', icon: GitBranch },
]

const stages = computed(() => {
  const source = manifest.value?.stages?.length ? manifest.value.stages : fallbackStages
  return source.map((stage) => ({ ...stage, icon: stageIcon[stage.key] || BrainCircuit }))
})
const papers = computed(() => result.value?.items ?? [])
const selectedPaper = computed(() => papers.value.find((paper) => paper.paper_id === selectedId.value) ?? null)
const searched = computed(() => result.value !== null)
const providerLabel = computed(() => result.value?.provider === 'arxiv' ? 'arXiv' : result.value?.provider ?? 'arXiv')
const harnessStage = computed(() => manifest.value?.stages?.find((stage) => stage.key === 'research_harness') ?? null)
const searchStage = computed(() => manifest.value?.stages?.find((stage) => stage.key === 'literature_search') ?? null)
const canUseHarness = computed(() => (harnessStage.value || searchStage.value)?.status === 'available')
const activeScope = computed(() => workspace.value?.scopes?.find((scope) => scope.scope_id === workspace.value?.active_scope_id) || null)
async function loadCapabilities() {
  capabilityLoading.value = true
  try {
    manifest.value = await getResearchAgentCapabilities(courseId.value)
  } catch (e) {
    notice.value = e?.message || '能力清单暂时无法读取'
  } finally {
    capabilityLoading.value = false
  }
}

async function loadWorkspace() {
  workspaceLoading.value = true
  try {
    workspace.value = await getResearchWorkspace(courseId.value, workspace.value?.workspace_id)
  } catch (e) {
    notice.value = e?.message || '科研工作区暂时无法读取'
  } finally {
    workspaceLoading.value = false
  }
}

async function executeHarness(action, payload, message) {
  if (!canUseHarness.value) {
    notice.value = '当前课程成员暂未获得科研 Harness 执行权限；工作台仍保持只读可见。'
    return null
  }
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const data = await runResearchHarness(courseId.value, {
      message,
      action,
      payload,
      workspace_id: workspace.value?.workspace_id || null,
      scope_id: workspace.value?.active_scope_id || null,
      context_budget_tokens: workspace.value?.context_budget_tokens || 4000,
    })
    harnessMeta.value = data
    if (data.workspace) workspace.value = data.workspace
    if (data.status === 'failed' || data.status === 'invalid_request') {
      error.value = data.message || '科研任务未完成。'
    } else if (data.status === 'degraded' || data.degraded_services?.length) {
      notice.value = data.message || '部分能力已降级，现有工作区状态保持不变。'
    } else {
      notice.value = data.message || '科研工作区已更新。'
    }
    return data
  } catch (e) {
    error.value = e?.message || '科研 Harness 执行失败，请稍后重试。'
    return null
  } finally {
    loading.value = false
  }
}

async function runSearch() {
  const normalized = query.value.trim()
  if (normalized.length < 2) {
    error.value = '请输入至少 2 个字符的研究主题。'
    return
  }
  const data = await executeHarness('literature_search', {}, normalized)
  if (!data) return
  result.value = {
    status: data.status,
    provider: data.search?.provider || 'arxiv',
    retrieved_at: data.search?.retrieved_at,
    items: data.papers || [],
    cache_hit: Boolean(data.search?.cache_hit),
  }
  selectedId.value = data.papers?.[0]?.paper_id ?? ''
}

function authorText(paper) {
  const authors = paper?.authors ?? []
  if (!authors.length) return '作者未记录'
  return authors.length > 3 ? `${authors.slice(0, 3).join('、')} 等` : authors.join('、')
}

function dateText(value) {
  if (!value) return '未记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN')
}

function openPaper() {
  if (selectedPaper.value?.source_url) window.open(selectedPaper.value.source_url, '_blank', 'noopener,noreferrer')
}

async function copyCitation() {
  const paper = selectedPaper.value
  if (!paper) return
  const citation = `${authorText(paper)}. ${paper.title}. arXiv:${paper.paper_id}, ${paper.year || 'n.d.'}.`
  try {
    await navigator.clipboard.writeText(citation)
    notice.value = '引用元数据已复制；提交前仍需按目标格式核验。'
  } catch {
    notice.value = '浏览器未允许复制，请从来源核验面板手动选择元数据。'
  }
}

async function createTodo(payload) {
  await executeHarness('todo_create', payload, `创建研究任务：${payload.title}`)
}

async function updateTodo(payload) {
  await executeHarness('todo_update', payload, '更新研究任务状态')
}

async function saveNote(payload) {
  await executeHarness('notepad_write', payload, `保存研究笔记：${payload.title}`)
}

async function storeMemory(payload) {
  const data = await executeHarness('memory_store', payload, '写入研究记忆')
  if (data?.tool_result?.embedding_status && data.tool_result.embedding_status !== 'available') {
    memoryRetrievalMode.value = 'keyword'
    notice.value = '记忆已保存；当前 embedding 未配置或不可用，检索将明确降级为关键词模式。'
  }
}

async function searchMemory(payload) {
  const data = await executeHarness('memory_search', payload, payload.query)
  const memoryResult = data?.tool_result || {}
  memoryResults.value = memoryResult.items || []
  memoryRetrievalMode.value = memoryResult.retrieval_mode || 'keyword'
}

async function createScope(payload) {
  await executeHarness('scope_create', payload, `创建子任务：${payload.title}`)
}

async function transitionScope(action, payload) {
  await executeHarness(action, payload, `${action}：${payload.scope_id}`)
}

function stageStatusLabel(status) {
  if (status === 'available') return '已接通'
  if (status === 'capability_required') return '需开启实验能力'
  if (status === 'permission_required') return '需要课程权限'
  return '研究预览'
}

onMounted(async () => {
  await Promise.allSettled([loadCapabilities(), loadWorkspace()])
})
</script>

<template>
  <div class="research-workspace">
    <aside class="research-rail" aria-label="科研工作台导航">
      <div class="rail-heading">
        <span class="sfx-t-title3">研究流程</span>
        <SfxBadge tone="ink">Harness</SfxBadge>
      </div>
      <ol class="stage-list">
        <li
          v-for="(stage, index) in stages"
          :key="stage.key"
          class="stage-item"
          :class="{ 'is-active': stage.key === 'research_harness', 'is-disabled': stage.status !== 'available' }"
        >
          <span class="stage-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <component :is="stage.icon" :size="17" />
          <span class="stage-copy">
            <strong>{{ stage.label }}</strong>
            <small>{{ stageStatusLabel(stage.status) }}</small>
          </span>
        </li>
      </ol>

      <div class="rail-divider"></div>
      <p class="rail-section-label">工作区</p>
      <nav class="workbench-nav" aria-label="Harness 工具">
        <SfxButton
          v-for="view in workbenchViews"
          :key="view.key"
          size="sm"
          :variant="activeView === view.key ? 'secondary' : 'tertiary'"
          @click="activeView = view.key"
        >
          <template #icon><component :is="view.icon" :size="16" /></template>
          {{ view.label }}
        </SfxButton>
      </nav>
      <p class="rail-policy sfx-t-caption">
        <ShieldCheck :size="15" />
        工具按意图、白名单与课程权限三重交集后注入。
      </p>
    </aside>

    <main class="research-main">
      <header class="research-header">
        <div>
          <div class="title-row">
            <h1 class="sfx-t-title1">科研工作台</h1>
            <SfxBadge tone="ink">HarnessEngineer</SfxBadge>
          </div>
          <p class="sfx-t-body sfx-t-secondary">用任务、笔记、作用域与可检索记忆组织证据优先的研究过程。</p>
        </div>
        <div v-if="activeScope" class="active-scope">
          <GitBranch :size="16" />
          <span><small>当前作用域</small><strong>{{ activeScope.title }}</strong></span>
        </div>
      </header>

      <div v-if="workspace" class="harness-strip sfx-t-caption">
        <span><strong>Workspace</strong> <span class="sfx-mono">{{ workspace.workspace_id.slice(0, 12) }}…</span></span>
        <span class="strip-dot">·</span>
        <span>Context {{ harnessMeta?.context?.estimated_tokens || 0 }} / {{ workspace.context_budget_tokens }}</span>
        <span class="strip-dot">·</span>
        <span>{{ harnessMeta?.context?.compressed ? '已自动压缩' : '窗口充足' }}</span>
        <span class="strip-dot">·</span>
        <span>{{ harnessMeta?.selected_tools?.length ? harnessMeta.selected_tools.join(' + ') : '等待任务' }}</span>
      </div>

      <div v-if="manifest && !canUseHarness" class="workspace-notice permission-notice sfx-t-caption">
        <ShieldCheck :size="15" />
        <span>当前课程成员暂未获得科研 Harness 执行权限。工作台仍可见，但写入与检索保持禁用。</span>
      </div>

      <SfxError v-if="error" variant="error" title="科研任务未完成" :description="error" :retryable="false" />
      <div v-else-if="notice" class="workspace-notice sfx-t-caption"><AlertTriangle :size="15" /> {{ notice }}</div>

      <section v-if="activeView === 'search'" class="workspace-view">
        <form class="search-form" role="search" @submit.prevent="runSearch">
          <label class="search-field">
            <Search :size="18" aria-hidden="true" />
            <input v-model="query" type="search" maxlength="300" autocomplete="off" placeholder="输入研究主题，例如 retrieval augmented generation education" aria-label="论文检索词" />
          </label>
          <SfxButton type="submit" variant="primary" :loading="loading" :disabled="!canUseHarness">检索论文</SfxButton>
        </form>
        <div class="source-strip sfx-t-caption">
          <BookOpen :size="15" /><span>{{ providerLabel }}</span><span class="strip-dot">·</span><span>仅检索论文元数据与摘要</span><span class="strip-dot">·</span><span>补充参考，不影响课程掌握度</span>
        </div>
        <section class="results-section" aria-live="polite">
          <div class="results-heading">
            <h2 class="sfx-t-title3">检索结果</h2>
            <span v-if="searched" class="sfx-t-caption">{{ papers.length }} 篇 · {{ result?.cache_hit ? '缓存命中' : '实时检索' }}</span>
          </div>
          <div v-if="loading" class="result-placeholder"><span class="placeholder-line is-wide"></span><span class="placeholder-line"></span><span class="placeholder-line is-wide"></span></div>
          <div v-else-if="!searched" class="empty-research"><LibraryBig :size="32" /><h3 class="sfx-t-title3">先定义一个可检索的研究主题</h3><p class="sfx-t-body sfx-t-secondary">检索将进入同一张 Harness LangGraph，并保留工具选择、上下文预算与来源边界。</p></div>
          <div v-else-if="papers.length === 0" class="empty-research"><Search :size="30" /><h3 class="sfx-t-title3">没有找到完整来源结果</h3><p class="sfx-t-body sfx-t-secondary">尝试使用英文术语、缩短检索词，或稍后再试。</p></div>
          <ol v-else class="paper-list">
            <li v-for="(paper, index) in papers" :key="paper.paper_id" class="paper-option">
              <input :id="`paper-${paper.paper_id}`" v-model="selectedId" type="radio" name="selected-paper" :value="paper.paper_id" />
              <label :for="`paper-${paper.paper_id}`" class="paper-row">
                <span class="paper-order">{{ index + 1 }}</span>
                <span class="paper-body"><span class="paper-title">{{ paper.title }}</span><span class="paper-abstract">{{ paper.abstract || '该条目未提供摘要。' }}</span><span class="paper-meta">{{ authorText(paper) }} · {{ paper.year || '年份未知' }}</span></span>
                <span class="paper-source"><SfxBadge tone="neutral">arXiv</SfxBadge><small>{{ paper.paper_id }}</small></span>
              </label>
            </li>
          </ol>
        </section>
      </section>

      <section v-else class="workspace-view harness-view">
        <ResearchTodoPanel v-if="activeView === 'todos'" :todos="workspace?.todos" :loading="loading" :disabled="!canUseHarness" @create="createTodo" @update="updateTodo" />
        <ResearchNotepadPanel v-else-if="activeView === 'notepad'" :notes="workspace?.notes" :active-scope-id="workspace?.active_scope_id" :loading="loading" :disabled="!canUseHarness" @save="saveNote" />
        <ResearchMemoryPanel v-else-if="activeView === 'memory'" :memories="workspace?.memories" :results="memoryResults" :retrieval-mode="memoryRetrievalMode" :loading="loading" :disabled="!canUseHarness" @store="storeMemory" @search="searchMemory" />
        <ResearchScopePanel v-else-if="activeView === 'scopes'" :scopes="workspace?.scopes" :active-scope-id="workspace?.active_scope_id" :loading="loading" :disabled="!canUseHarness" @create="createScope" @transition="transitionScope" />
      </section>
    </main>

    <aside class="evidence-inspector" aria-label="研究状态与来源核验">
      <template v-if="activeView === 'search'">
        <div class="inspector-title"><ShieldCheck :size="20" /><h2 class="sfx-t-title2">来源核验</h2></div>
        <template v-if="selectedPaper">
          <h3 class="selected-title">{{ selectedPaper.title }}</h3>
          <dl class="source-facts">
            <div><dt>Provider</dt><dd>arXiv</dd></div><div><dt>Paper ID</dt><dd class="sfx-mono">{{ selectedPaper.paper_id }}</dd></div><div><dt>Published</dt><dd>{{ dateText(selectedPaper.published_at) }}</dd></div><div><dt>Authors</dt><dd>{{ authorText(selectedPaper) }}</dd></div><div><dt>Retrieved</dt><dd>{{ dateText(result?.retrieved_at) }}</dd></div><div v-if="selectedPaper.doi"><dt>DOI</dt><dd class="sfx-mono">{{ selectedPaper.doi }}</dd></div>
          </dl>
          <div class="inspector-actions"><SfxButton variant="secondary" size="sm" @click="openPaper"><template #icon><ExternalLink :size="15" /></template>查看原文</SfxButton><SfxButton variant="secondary" size="sm" @click="copyCitation"><template #icon><Clipboard :size="15" /></template>复制元数据</SfxButton></div>
          <section class="boundary-section"><h3 class="sfx-t-title3">使用边界</h3><ul><li><Check :size="15" /> 仅作补充参考</li><li><Check :size="15" /> 不写入学习掌握度</li><li><Check :size="15" /> 不直接写入课程图谱</li></ul></section>
          <div class="verification-warning sfx-t-caption"><AlertTriangle :size="17" />尚未执行全文核验、撤稿状态检查或复现验证。</div>
        </template>
        <div v-else class="inspector-empty"><ShieldCheck :size="28" /><p class="sfx-t-body sfx-t-secondary">选择一篇论文后，在这里核验来源与使用边界。</p></div>
      </template>

      <template v-else>
        <div class="inspector-title"><BrainCircuit :size="20" /><h2 class="sfx-t-title2">Harness 状态</h2></div>
        <dl class="source-facts harness-facts">
          <div><dt>Scope</dt><dd>{{ activeScope?.title || '主研究作用域' }}</dd></div>
          <div><dt>Route</dt><dd class="sfx-mono">{{ harnessMeta?.graph_route || 'idle' }}</dd></div>
          <div><dt>Prompt</dt><dd class="sfx-mono">{{ harnessMeta?.prompt?.version || 'research-harness/1' }}</dd></div>
          <div><dt>Context</dt><dd>{{ harnessMeta?.context?.estimated_tokens || 0 }} / {{ workspace?.context_budget_tokens || 4000 }} tokens</dd></div>
          <div><dt>Compression</dt><dd>{{ harnessMeta?.context?.compressed ? 'extractive' : 'not required' }}</dd></div>
        </dl>
        <section class="boundary-section">
          <h3 class="sfx-t-title3">动态工具</h3>
          <div v-if="harnessMeta?.selected_tools?.length" class="tool-badges"><SfxBadge v-for="tool in harnessMeta.selected_tools" :key="tool" tone="ink">{{ tool }}</SfxBadge></div>
          <p v-else class="sfx-t-body sfx-t-secondary">执行任务后显示本轮经白名单与权限交集选中的工具。</p>
        </section>
        <section class="boundary-section"><h3 class="sfx-t-title3">安全边界</h3><ul><li><Check :size="15" /> API 与 Tool 双重授权</li><li><Check :size="15" /> 不开放主机命令执行</li><li><Check :size="15" /> Prompt 正文不进入响应</li></ul></section>
        <div v-if="harnessMeta?.degraded_services?.length" class="verification-warning sfx-t-caption"><AlertTriangle :size="17" />降级：{{ harnessMeta.degraded_services.join('、') }}</div>
      </template>
    </aside>
  </div>
</template>

<style scoped>
.research-workspace { flex: 1; min-height: 0; display: grid; grid-template-columns: 205px minmax(0, 1fr) 320px; background: var(--surface-page); overflow: hidden; }
.research-rail, .evidence-inspector { min-height: 0; overflow-y: auto; background: var(--surface-panel); }
.research-rail { border-right: 1px solid var(--border-default); padding: var(--space-5) var(--space-3); display: flex; flex-direction: column; }
.rail-heading, .title-row, .results-heading, .inspector-title { display: flex; align-items: center; gap: var(--space-2); }
.rail-heading { justify-content: space-between; margin-bottom: var(--space-4); padding: 0 var(--space-2); }
.stage-list { display: flex; flex-direction: column; gap: 2px; }
.stage-item { position: relative; display: grid; grid-template-columns: 24px 19px minmax(0, 1fr); align-items: center; gap: var(--space-2); padding: var(--space-2); color: var(--text-secondary); }
.stage-item::before { position: absolute; inset: 5px auto 5px 0; width: 2px; content: ''; background: transparent; }
.stage-item.is-active { color: var(--ink-900); background: var(--ink-100); }
.stage-item.is-active::before { background: var(--ink-700); }
.stage-item.is-disabled { color: var(--text-muted); }
.stage-index { font-family: var(--font-mono); font-size: var(--caption-size); }
.stage-copy { display: flex; min-width: 0; flex-direction: column; gap: 1px; }
.stage-copy strong { font-size: var(--ui-sm-size); font-weight: 600; }
.stage-copy small { color: var(--amber-700); font-size: var(--caption-size); }
.stage-item.is-active .stage-copy small, .stage-item:not(.is-disabled) .stage-copy small { color: var(--green-700); }
.rail-divider { height: 1px; background: var(--border-default); margin: var(--space-4) var(--space-2); }
.rail-section-label { padding: 0 var(--space-2); margin-bottom: var(--space-2); color: var(--text-muted); font-size: var(--caption-size); font-weight: 600; letter-spacing: .08em; text-transform: uppercase; }
.workbench-nav { display: flex; flex-direction: column; align-items: stretch; gap: 2px; }
.workbench-nav :deep(.sfx-btn) { width: 100%; justify-content: flex-start; }
.rail-policy { display: flex; align-items: flex-start; gap: var(--space-2); margin-top: auto; padding: var(--space-3); border: 1px solid var(--border-default); border-radius: var(--radius-md); }
.research-main { min-width: 0; min-height: 0; overflow-y: auto; padding: var(--space-6) var(--space-6) var(--space-12); }
.research-header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-5); margin-bottom: var(--space-4); }
.title-row { margin-bottom: var(--space-2); }
.active-scope { display: flex; align-items: center; gap: var(--space-2); min-width: 180px; padding: var(--space-3); border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--surface-panel); color: var(--ink-700); }
.active-scope span { display: flex; flex-direction: column; gap: 2px; }
.active-scope small { color: var(--text-muted); font-size: var(--caption-size); }
.active-scope strong { font-size: var(--ui-sm-size); }
.harness-strip, .source-strip { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); color: var(--text-muted); }
.harness-strip { padding: var(--space-3); margin-bottom: var(--space-4); border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--surface-panel); }
.search-form { display: flex; gap: var(--space-3); align-items: stretch; }
.search-field { flex: 1; min-width: 0; display: flex; align-items: center; gap: var(--space-2); height: var(--control-height); padding: 0 var(--space-3); background: var(--surface-panel); border: 1px solid var(--border-strong); border-radius: var(--radius-md); color: var(--text-muted); }
.search-field:focus-within { border-color: var(--ink-500); box-shadow: 0 0 0 2px var(--ink-100); }
.search-field input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--text-primary); font: inherit; }
.source-strip { padding: var(--space-3) 0 var(--space-4); border-bottom: 1px solid var(--border-default); }
.strip-dot { color: var(--text-disabled); }
.workspace-notice, .verification-warning { display: flex; align-items: flex-start; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--amber-300); border-radius: var(--radius-md); color: var(--amber-700); background: var(--amber-100); }
.workspace-notice { margin-bottom: var(--space-4); }
.permission-notice { margin-top: var(--space-4); }
.workspace-view { min-height: 0; }
.harness-view { padding-top: var(--space-2); }
.results-section { margin-top: var(--space-5); }
.results-heading { justify-content: space-between; margin-bottom: var(--space-2); }
.paper-list { border-top: 1px solid var(--border-default); }
.paper-option { position: relative; border-bottom: 1px solid var(--border-default); }
.paper-option input { position: absolute; opacity: 0; pointer-events: none; }
.paper-row { position: relative; display: grid; grid-template-columns: 24px minmax(0, 1fr) 110px; gap: var(--space-3); padding: var(--space-4) var(--space-2); cursor: pointer; }
.paper-row::before { position: absolute; inset: 4px auto 4px 0; width: 2px; content: ''; background: transparent; }
.paper-row:hover { background: var(--surface-cool); }
.paper-option input:focus-visible + .paper-row { outline: 2px solid var(--ink-500); outline-offset: -2px; }
.paper-option input:checked + .paper-row { background: var(--surface-panel); }
.paper-option input:checked + .paper-row::before { background: var(--ink-700); }
.paper-order { color: var(--text-muted); font-size: var(--ui-sm-size); }
.paper-body { display: flex; flex-direction: column; gap: var(--space-2); min-width: 0; }
.paper-title { color: var(--ink-900); font-size: var(--body-md-size); font-weight: 650; line-height: 1.35; }
.paper-abstract { color: var(--text-secondary); font-size: var(--body-md-size); line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.paper-meta { color: var(--text-muted); font-size: var(--caption-size); }
.paper-source { display: flex; align-items: flex-end; flex-direction: column; gap: var(--space-2); color: var(--text-muted); }
.paper-source small { font-family: var(--font-mono); overflow-wrap: anywhere; text-align: right; }
.empty-research { min-height: 280px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; gap: var(--space-3); color: var(--text-muted); }
.empty-research p { max-width: 560px; }
.result-placeholder { display: flex; flex-direction: column; gap: var(--space-4); padding-top: var(--space-4); }
.placeholder-line { height: 66px; width: 84%; background: var(--surface-cool); border-radius: var(--radius-sm); }
.placeholder-line.is-wide { width: 100%; }
.evidence-inspector { border-left: 1px solid var(--border-default); padding: var(--space-5); }
.inspector-title { margin-bottom: var(--space-5); }
.selected-title { color: var(--ink-900); font-size: var(--body-lg-size); line-height: 1.45; margin-bottom: var(--space-5); }
.source-facts { display: flex; flex-direction: column; gap: var(--space-4); }
.source-facts div { display: grid; grid-template-columns: 84px minmax(0, 1fr); gap: var(--space-3); }
.source-facts dt { color: var(--text-muted); font-size: var(--ui-sm-size); }
.source-facts dd { min-width: 0; color: var(--text-primary); font-size: var(--body-md-size); overflow-wrap: anywhere; }
.inspector-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); padding: var(--space-5) 0; margin-top: var(--space-5); border-top: 1px solid var(--border-default); border-bottom: 1px solid var(--border-default); }
.boundary-section { padding: var(--space-5) 0; border-top: 1px solid var(--border-default); margin-top: var(--space-5); }
.boundary-section ul { display: flex; flex-direction: column; gap: var(--space-3); margin-top: var(--space-4); }
.boundary-section li { display: flex; align-items: center; gap: var(--space-2); color: var(--text-secondary); font-size: var(--body-md-size); }
.boundary-section li svg { color: var(--green-700); }
.tool-badges { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-3); }
.inspector-empty { min-height: 360px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-3); text-align: center; color: var(--text-muted); }
@media (max-width: 1180px) { .research-workspace { grid-template-columns: 190px minmax(0, 1fr) 280px; } .research-main, .evidence-inspector { padding-left: var(--space-4); padding-right: var(--space-4); } .paper-row { grid-template-columns: 20px minmax(0, 1fr); } .paper-source { grid-column: 2; flex-direction: row; align-items: center; } }
@media (max-width: 900px) { .research-workspace { display: flex; flex-direction: column; overflow-y: auto; } .research-rail, .research-main, .evidence-inspector { flex: none; overflow: visible; } .research-rail { border-right: 0; border-bottom: 1px solid var(--border-default); } .stage-list { display: none; } .workbench-nav { display: grid; grid-template-columns: repeat(2, 1fr); } .rail-policy { margin-top: var(--space-4); } .evidence-inspector { border-left: 0; border-top: 1px solid var(--border-default); } .research-header { flex-direction: column; } .active-scope { width: 100%; } }
</style>
