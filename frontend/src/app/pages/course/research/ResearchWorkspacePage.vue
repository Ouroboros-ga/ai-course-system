<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import {
  AlertTriangle,
  BarChart3,
  BookOpen,
  Check,
  Clipboard,
  Code2,
  ExternalLink,
  FilePenLine,
  LibraryBig,
  Network,
  Search,
  ShieldCheck,
} from 'lucide-vue-next'
import { getResearchAgentCapabilities, searchResearchPapers } from '@/api/research_agent.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'

const { courseId } = inject('courseContext')

const query = ref('')
const loading = ref(false)
const capabilityLoading = ref(true)
const error = ref('')
const notice = ref('')
const result = ref(null)
const manifest = ref(null)
const selectedId = ref('')

const fallbackStages = [
  { key: 'literature_search', label: '文献检索', status: 'available', icon: LibraryBig },
  { key: 'trend_analysis', label: '趋势分析', status: 'research_preview', icon: BarChart3 },
  { key: 'evidence_synthesis', label: '证据综合', status: 'research_preview', icon: Network },
  { key: 'writing_assist', label: '学术写作', status: 'research_preview', icon: FilePenLine },
  { key: 'code_reproduction', label: '代码复现', status: 'research_preview', icon: Code2 },
]

const stageIcon = {
  literature_search: LibraryBig,
  trend_analysis: BarChart3,
  evidence_synthesis: Network,
  writing_assist: FilePenLine,
  code_reproduction: Code2,
}

const stages = computed(() => {
  const source = manifest.value?.stages?.length ? manifest.value.stages : fallbackStages
  return source.map((stage) => ({ ...stage, icon: stageIcon[stage.key] }))
})
const papers = computed(() => result.value?.items ?? [])
const selectedPaper = computed(() => papers.value.find((paper) => paper.paper_id === selectedId.value) ?? null)
const searched = computed(() => result.value !== null)
const providerLabel = computed(() => result.value?.provider === 'arxiv' ? 'arXiv' : result.value?.provider ?? 'arXiv')
const searchStage = computed(() => manifest.value?.stages?.find((stage) => stage.key === 'literature_search') ?? null)
const canSearch = computed(() => searchStage.value?.status === 'available')

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

async function runSearch() {
  if (!canSearch.value) {
    notice.value = '当前课程成员暂未获得论文检索权限；你仍可查看研究工作台与能力预览。'
    return
  }
  const normalized = query.value.trim()
  if (normalized.length < 2) {
    error.value = '请输入至少 2 个字符的研究主题。'
    return
  }
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const data = await searchResearchPapers(courseId.value, {
      query: normalized,
      max_results: 8,
    })
    result.value = data
    selectedId.value = data.items?.[0]?.paper_id ?? ''
    if (data.status === 'degraded') {
      notice.value = data.message || '学术检索服务暂时不可用。'
    }
  } catch (e) {
    error.value = e?.message || '论文检索失败，请稍后重试。'
    result.value = null
    selectedId.value = ''
  } finally {
    loading.value = false
  }
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
  if (selectedPaper.value?.source_url) {
    window.open(selectedPaper.value.source_url, '_blank', 'noopener,noreferrer')
  }
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

onMounted(loadCapabilities)
</script>

<template>
  <div class="research-workspace">
    <aside class="research-rail" aria-label="研究流程">
      <div class="rail-heading">
        <span class="sfx-t-title3">研究流程</span>
        <SfxBadge tone="amber">Preview</SfxBadge>
      </div>
      <ol class="stage-list">
        <li
          v-for="(stage, index) in stages"
          :key="stage.key"
          class="stage-item"
          :class="{ 'is-active': stage.key === 'literature_search', 'is-disabled': stage.status !== 'available' }"
        >
          <span class="stage-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <component :is="stage.icon" :size="18" />
          <span class="stage-copy">
            <strong>{{ stage.label }}</strong>
            <small>{{ stage.status === 'available' ? '已接通' : stage.status === 'capability_required' ? '需开启实验能力' : '即将开放' }}</small>
          </span>
        </li>
      </ol>
      <p class="rail-policy sfx-t-caption">
        <ShieldCheck :size="15" />
        其他能力将在证据链与执行隔离验证完成后开放。
      </p>
    </aside>

    <main class="research-main">
      <header class="research-header">
        <div>
          <div class="title-row">
            <h1 class="sfx-t-title1">研究工作台</h1>
            <SfxBadge tone="amber">Research Preview</SfxBadge>
          </div>
          <p class="sfx-t-body sfx-t-secondary">从可验证论文开始，构建可追溯的研究证据链。</p>
        </div>
      </header>

      <form class="search-form" role="search" @submit.prevent="runSearch">
        <label class="search-field">
          <Search :size="18" aria-hidden="true" />
          <input
            v-model="query"
            type="search"
            maxlength="300"
            autocomplete="off"
            placeholder="输入研究主题，例如 retrieval augmented generation education"
            aria-label="论文检索词"
          />
        </label>
        <SfxButton type="submit" variant="primary" :loading="loading" :disabled="!canSearch">检索论文</SfxButton>
      </form>

      <div v-if="manifest && !canSearch" class="workspace-notice permission-notice sfx-t-caption">
        <ShieldCheck :size="15" />
        <span>当前课程成员暂未获得论文检索权限。研究工作台仍可见，待课程管理员开启后即可检索。</span>
      </div>

      <div class="source-strip sfx-t-caption">
        <BookOpen :size="15" />
        <span>{{ providerLabel }}</span>
        <span class="strip-dot">·</span>
        <span>仅检索论文元数据与摘要</span>
        <span class="strip-dot">·</span>
        <span>补充参考，不影响课程掌握度</span>
      </div>

      <SfxError
        v-if="error"
        variant="error"
        title="检索未完成"
        :description="error"
        :retryable="false"
      />
      <div v-else-if="notice" class="workspace-notice sfx-t-caption">
        <AlertTriangle :size="15" /> {{ notice }}
      </div>

      <section class="results-section" aria-live="polite">
        <div class="results-heading">
          <h2 class="sfx-t-title3">检索结果</h2>
          <span v-if="searched" class="sfx-t-caption">{{ papers.length }} 篇 · {{ result?.cache_hit ? '缓存命中' : '实时检索' }}</span>
        </div>

        <div v-if="loading" class="result-placeholder">
          <span class="placeholder-line is-wide"></span>
          <span class="placeholder-line"></span>
          <span class="placeholder-line is-wide"></span>
        </div>
        <div v-else-if="!searched" class="empty-research">
          <LibraryBig :size="32" />
          <h3 class="sfx-t-title3">先定义一个可检索的研究主题</h3>
          <p class="sfx-t-body sfx-t-secondary">当前切片接通 arXiv。结果只代表元数据命中，不能替代全文阅读、同行评议状态检查或代码复现。</p>
        </div>
        <div v-else-if="papers.length === 0" class="empty-research">
          <Search :size="30" />
          <h3 class="sfx-t-title3">没有找到完整来源结果</h3>
          <p class="sfx-t-body sfx-t-secondary">尝试使用英文术语、缩短检索词，或稍后再试。</p>
        </div>
        <ol v-else class="paper-list">
          <li v-for="(paper, index) in papers" :key="paper.paper_id" class="paper-option">
            <input
              :id="`paper-${paper.paper_id}`"
              v-model="selectedId"
              type="radio"
              name="selected-paper"
              :value="paper.paper_id"
            />
            <label :for="`paper-${paper.paper_id}`" class="paper-row">
              <span class="paper-order">{{ index + 1 }}</span>
              <span class="paper-body">
                <span class="paper-title">{{ paper.title }}</span>
                <span class="paper-abstract">{{ paper.abstract || '该条目未提供摘要。' }}</span>
                <span class="paper-meta">{{ authorText(paper) }} · {{ paper.year || '年份未知' }}</span>
              </span>
              <span class="paper-source">
                <SfxBadge tone="neutral">arXiv</SfxBadge>
                <small>{{ paper.paper_id }}</small>
              </span>
            </label>
          </li>
        </ol>
      </section>
    </main>

    <aside class="evidence-inspector" aria-label="来源核验">
      <div class="inspector-title">
        <ShieldCheck :size="20" />
        <h2 class="sfx-t-title2">来源核验</h2>
      </div>

      <template v-if="selectedPaper">
        <h3 class="selected-title">{{ selectedPaper.title }}</h3>
        <dl class="source-facts">
          <div><dt>Provider</dt><dd>arXiv</dd></div>
          <div><dt>Paper ID</dt><dd class="sfx-mono">{{ selectedPaper.paper_id }}</dd></div>
          <div><dt>Published</dt><dd>{{ dateText(selectedPaper.published_at) }}</dd></div>
          <div><dt>Authors</dt><dd>{{ authorText(selectedPaper) }}</dd></div>
          <div><dt>Retrieved</dt><dd>{{ dateText(result?.retrieved_at) }}</dd></div>
          <div v-if="selectedPaper.doi"><dt>DOI</dt><dd class="sfx-mono">{{ selectedPaper.doi }}</dd></div>
        </dl>
        <div class="inspector-actions">
          <SfxButton variant="secondary" size="sm" @click="openPaper">
            <template #icon><ExternalLink :size="15" /></template>
            查看原文
          </SfxButton>
          <SfxButton variant="secondary" size="sm" @click="copyCitation">
            <template #icon><Clipboard :size="15" /></template>
            复制元数据
          </SfxButton>
        </div>

        <section class="boundary-section">
          <h3 class="sfx-t-title3">使用边界</h3>
          <ul>
            <li><Check :size="15" /> 仅作补充参考</li>
            <li><Check :size="15" /> 不写入学习掌握度</li>
            <li><Check :size="15" /> 不直接写入课程图谱</li>
          </ul>
        </section>
        <div class="verification-warning sfx-t-caption">
          <AlertTriangle :size="17" />
          尚未执行全文核验、撤稿状态检查或复现验证。
        </div>
      </template>
      <div v-else class="inspector-empty">
        <ShieldCheck :size="28" />
        <p class="sfx-t-body sfx-t-secondary">选择一篇论文后，在这里核验来源与使用边界。</p>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.research-workspace {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 190px minmax(0, 1fr) 330px;
  background: var(--surface-page);
  overflow: hidden;
}

.research-rail,
.evidence-inspector {
  min-height: 0;
  overflow-y: auto;
  background: var(--surface-panel);
}

.research-rail {
  border-right: 1px solid var(--border-default);
  padding: var(--space-6) var(--space-4);
  display: flex;
  flex-direction: column;
}

.rail-heading,
.title-row,
.results-heading,
.inspector-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.rail-heading { justify-content: space-between; margin-bottom: var(--space-5); }
.stage-list { display: flex; flex-direction: column; gap: var(--space-1); }
.stage-item {
  display: grid;
  grid-template-columns: 26px 20px minmax(0, 1fr);
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-2);
  color: var(--text-secondary);
  border-left: 2px solid transparent;
}
.stage-item.is-active {
  color: var(--ink-900);
  background: var(--ink-100);
  border-left-color: var(--ink-700);
}
.stage-item.is-disabled { color: var(--text-muted); }
.stage-index { font-family: var(--font-mono); font-size: 11px; }
.stage-copy { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.stage-copy strong { font-size: var(--ui-sm-size); font-weight: 600; }
.stage-copy small { color: var(--amber-700); font-size: 11px; }
.stage-item.is-active .stage-copy small { color: var(--green-700); }
.rail-policy {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin-top: auto;
  padding: var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
}

.research-main {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-7) var(--space-6) var(--space-12);
}
.research-header { margin-bottom: var(--space-5); }
.title-row { margin-bottom: var(--space-2); }
.search-form { display: flex; gap: var(--space-3); align-items: stretch; }
.search-field {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: var(--control-height);
  padding: 0 var(--space-3);
  background: var(--surface-panel);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  color: var(--text-muted);
}
.search-field:focus-within { border-color: var(--ink-500); box-shadow: 0 0 0 2px var(--ink-100); }
.search-field input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--text-primary); font: inherit; }
.source-strip {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) 0 var(--space-4);
  border-bottom: 1px solid var(--border-default);
}
.strip-dot { color: var(--text-disabled); }
.workspace-notice,
.verification-warning {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--amber-300);
  border-radius: var(--radius-md);
  color: var(--amber-700);
  background: var(--amber-100);
}
.workspace-notice { margin-top: var(--space-4); }
.permission-notice { margin-bottom: var(--space-4); }
.results-section { margin-top: var(--space-5); }
.results-heading { justify-content: space-between; margin-bottom: var(--space-2); }
.paper-list { border-top: 1px solid var(--border-default); }
.paper-option { position: relative; border-bottom: 1px solid var(--border-default); }
.paper-option input { position: absolute; opacity: 0; pointer-events: none; }
.paper-row {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) 110px;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-2);
  cursor: pointer;
  border-left: 2px solid transparent;
}
.paper-row:hover { background: var(--surface-cool); }
.paper-option input:focus-visible + .paper-row { outline: 2px solid var(--ink-500); outline-offset: -2px; }
.paper-option input:checked + .paper-row { background: var(--surface-panel); border-left-color: var(--ink-700); }
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

.evidence-inspector { border-left: 1px solid var(--border-default); padding: var(--space-6); }
.inspector-title { margin-bottom: var(--space-5); }
.selected-title { color: var(--ink-900); font-size: var(--body-lg-size); line-height: 1.45; margin-bottom: var(--space-5); }
.source-facts { display: flex; flex-direction: column; gap: var(--space-4); }
.source-facts div { display: grid; grid-template-columns: 88px minmax(0, 1fr); gap: var(--space-3); }
.source-facts dt { color: var(--text-muted); font-size: var(--ui-sm-size); }
.source-facts dd { min-width: 0; color: var(--text-primary); font-size: var(--body-md-size); overflow-wrap: anywhere; }
.inspector-actions { display: flex; gap: var(--space-2); padding: var(--space-5) 0; margin-top: var(--space-5); border-top: 1px solid var(--border-default); border-bottom: 1px solid var(--border-default); }
.boundary-section { padding: var(--space-5) 0; }
.boundary-section ul { display: flex; flex-direction: column; gap: var(--space-3); margin-top: var(--space-4); }
.boundary-section li { display: flex; align-items: center; gap: var(--space-2); color: var(--text-secondary); font-size: var(--body-md-size); }
.boundary-section li svg { color: var(--green-700); }
.inspector-empty { min-height: 360px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-3); text-align: center; color: var(--text-muted); }

@media (max-width: 1180px) {
  .research-workspace { grid-template-columns: 168px minmax(0, 1fr) 280px; }
  .research-main, .evidence-inspector { padding-left: var(--space-4); padding-right: var(--space-4); }
  .paper-row { grid-template-columns: 20px minmax(0, 1fr); }
  .paper-source { grid-column: 2; flex-direction: row; align-items: center; }
}
</style>
