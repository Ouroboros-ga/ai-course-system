<script setup>
/**
 * XH-202620 学科知识库检索页（CS 垂类）。
 *
 * 双模式：精编概念（默认兼容）/ 资料检索（版本化语料原文块）。
 * 数据源：GET /api/v1/discipline-knowledge/*；资料模式只调用 chunk 引用
 * 端点取原文（固定 release_id），不拼磁盘路径。
 * 设计遵循 design.md：三层滚动模型（本页为 L3，根容器 height:100% + 内部滚动）、
 * 语义令牌（--color-brand / --surface-panel / --border-default 等）、SfxButton 规范。
 */
import { computed, onMounted, ref } from 'vue'
import { BookOpen, ChevronDown, ChevronUp, FileText, RefreshCw, Search, Sparkles } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'
import {
  getDisciplineCorpusChunk,
  getDisciplineKnowledgeOverview,
  getDisciplineKnowledgeNode,
  searchDisciplineKnowledge,
  reloadDisciplineKnowledge,
} from '@/api/disciplineKnowledge.js'
import { formatCorpusCoverage, safeSourceUrl } from '@/app/lib/disciplineCorpusPresentation.js'

const query = ref('')
const topK = ref(5)
const mode = ref('concept') // concept | corpus | all
const loading = ref(false)
const error = ref('')
const results = ref([])
const overview = ref(null)
const expanded = ref(null) // 展开的节点 id
const nodeDetail = ref(null)
const degradedReasons = ref([])
const releaseId = ref('')
const expandedChunk = ref(null) // 展开原文的 chunk_id
const chunkText = ref(null)
const chunkLoading = ref(false)
const chunkError = ref('')

const hasSearched = ref(false)

const nodeTypeLabel = (type) => ({
  concept: '概念',
  method: '方法',
  definition: '定义',
  theorem: '定理',
  formula: '公式',
  skill: '技能',
}[type] || type || '知识')

async function loadOverview() {
  try {
    // request.js 拦截器已剥离 code/message 层，返回的即 data（overview dict）
    const body = await getDisciplineKnowledgeOverview()
    overview.value = body ?? null
  } catch {
    overview.value = null
  }
}

async function runSearch() {
  const q = query.value.trim()
  if (!q) return
  loading.value = true
  error.value = ''
  hasSearched.value = true
  expanded.value = null
  nodeDetail.value = null
  degradedReasons.value = []
  releaseId.value = ''
  expandedChunk.value = null
  chunkText.value = null
  chunkError.value = ''
  try {
    const body = await searchDisciplineKnowledge(q, topK.value, mode.value)
    results.value = body?.results ?? []
    releaseId.value = body?.release_id ?? ''
    degradedReasons.value = body?.degraded_reasons ?? []
  } catch (err) {
    error.value = err?.response?.data?.detail || '检索失败，请稍后重试。'
    results.value = []
  } finally {
    loading.value = false
  }
}

function isCorpusRow(row) {
  return row?.result_type === 'corpus_chunk'
}

const conceptResults = computed(() => results.value.filter((row) => !isCorpusRow(row)))
const corpusResults = computed(() => results.value.filter(isCorpusRow))

async function toggleChunkDetail(row) {
  const key = row.chunk_id
  if (expandedChunk.value === key && chunkText.value) {
    expandedChunk.value = null
    chunkText.value = null
    return
  }
  expandedChunk.value = key
  chunkText.value = null
  chunkError.value = ''
  if (!key || !releaseId.value) {
    chunkError.value = '缺少引用身份，无法查看原文。'
    return
  }
  chunkLoading.value = true
  try {
    const body = await getDisciplineCorpusChunk(key, releaseId.value)
    chunkText.value = body ?? null
  } catch (err) {
    chunkError.value = err?.response?.status === 410
      ? '该来源已撤回，不再展示原文。'
      : '原文加载失败，请稍后重试。'
    chunkText.value = null
  } finally {
    chunkLoading.value = false
  }
}

function switchMode(next) {
  if (mode.value === next) return
  mode.value = next
  hasSearched.value = false
  results.value = []
  degradedReasons.value = []
  releaseId.value = ''
  expandedChunk.value = null
  chunkText.value = null
}

async function toggleDetail(node) {
  if (expanded.value === node.id && nodeDetail.value) {
    expanded.value = null
    nodeDetail.value = null
    return
  }
  expanded.value = node.id
  nodeDetail.value = null
  try {
    const body = await getDisciplineKnowledgeNode(node.id)
    nodeDetail.value = body ?? null
  } catch {
    nodeDetail.value = null
  }
}

// 点击整张知识卡片：未展开时自动展开详情；已展开时保持现状（收起走标题栏按钮/箭头）
async function handleCardClick(node) {
  if (expanded.value === node.id) return
  await toggleDetail(node)
}

async function refreshData() {
  try {
    await reloadDisciplineKnowledge()
  } catch {
    /* 只读场景下重载失败不阻塞 */
  }
  await loadOverview()
}

onMounted(loadOverview)

const overviewText = computed(() => {
  if (!overview.value) return ''
  return `${overview.value.node_count} 精编概念 · ${overview.value.relation_count} 关系 · ${Object.keys(overview.value.courses || {}).length} 门课`
})

const corpusCoverageText = computed(() => {
  if (!overview.value) return ''
  return formatCorpusCoverage(overview.value.corpus ?? null)
})
</script>

<template>
  <div class="dk-page">
    <header class="dk-header">
      <div class="dk-title-row">
        <h1 class="dk-title">CS 学科知识库</h1>
        <span v-if="overviewText" class="dk-overview">{{ overviewText }}</span>
        <span v-if="corpusCoverageText" class="dk-overview dk-corpus-coverage">{{ corpusCoverageText }}</span>
        <SfxButton variant="tertiary" size="sm" class="dk-refresh" @click="refreshData">
          <RefreshCw :size="14" /> 刷新
        </SfxButton>
      </div>
      <div class="dk-modes" role="tablist" aria-label="检索模式">
        <SfxButton :variant="mode === 'concept' ? 'secondary' : 'tertiary'" size="sm" @click="switchMode('concept')">
          <Sparkles :size="14" /> 精编概念
        </SfxButton>
        <SfxButton :variant="mode === 'corpus' ? 'secondary' : 'tertiary'" size="sm" @click="switchMode('corpus')">
          <FileText :size="14" /> 资料检索
        </SfxButton>
        <SfxButton :variant="mode === 'all' ? 'secondary' : 'tertiary'" size="sm" @click="switchMode('all')">
          <Search :size="14" /> 全部
        </SfxButton>
      </div>
      <form class="dk-search" @submit.prevent="runSearch">
        <div class="dk-search-input-wrap">
          <Search :size="16" class="dk-search-icon" />
          <input
            v-model="query"
            class="dk-search-input"
            type="search"
            placeholder="检索学科知识，如：哈希表 / quick sort / TCP 三次握手 / 事务 ACID"
            aria-label="学科知识检索"
          />
        </div>
        <select v-model.number="topK" class="dk-topk" aria-label="结果数量">
          <option :value="5">5 条</option>
          <option :value="10">10 条</option>
          <option :value="20">20 条</option>
        </select>
        <SfxButton type="submit" :loading="loading">检索</SfxButton>
      </form>
    </header>

    <div class="dk-body">
      <p v-if="error" class="dk-error">{{ error }}</p>

      <p v-else-if="loading" class="dk-hint"><span class="dk-spinner" /> 检索中…</p>

      <p v-else-if="hasSearched && results.length === 0" class="dk-hint">
        {{ mode === 'concept' ? '未找到匹配的知识节点，请尝试其他关键词。' : '未找到匹配的语料段落，请尝试其他关键词。' }}
      </p>

      <p v-else-if="!hasSearched" class="dk-hint">
        输入关键词检索 CS 学科知识库；精编概念附带<b>权威来源</b>（教材/标准/论文），可追溯可核查。
        资料检索返回版本化语料原文块，可打开出处查看定位。
      </p>

      <template v-if="hasSearched && !loading && !error">
        <p v-if="degradedReasons.length" class="dk-hint dk-degraded">
          部分通路降级：{{ degradedReasons.join('、') }}；当前仅展示可用通路结果。
        </p>
        <p v-if="releaseId" class="dk-hint dk-release">语料版本：{{ releaseId }}</p>
      </template>

      <!-- 概念/语料结果各自独立 v-if：不得挂在提示 template 的 v-else-if 上，
           否则检索成功后概念卡永远不渲染（2026-09-08 全量审核 P1-2）。 -->
      <ul v-if="conceptResults.length && !loading" class="dk-results">
        <!-- 整卡可点：未展开时自动展开详情；标题按钮保持可收起（@click.stop 防冒泡） -->
        <li
          v-for="node in conceptResults"
          :key="node.id"
          class="dk-card"
          :class="{ 'dk-card--expanded': expanded === node.id }"
          @click="handleCardClick(node)"
        >
          <button
            type="button"
            class="dk-card-head"
            :aria-expanded="expanded === node.id"
            @click.stop="toggleDetail(node)"
          >
            <span class="dk-card-name">{{ node.name }}</span>
            <span class="dk-card-type">{{ nodeTypeLabel(node.node_type) }}</span>
            <span class="dk-card-score">{{ node.score?.toFixed?.(2) }}</span>
            <component :is="expanded === node.id ? ChevronUp : ChevronDown" :size="16" class="dk-chevron" />
          </button>

          <p class="dk-card-def">{{ node.definition }}</p>

          <ul v-if="node.key_points?.length" class="dk-card-points">
            <li v-for="point in node.key_points.slice(0, 4)" :key="point">{{ point }}</li>
          </ul>

          <div class="dk-card-meta">
            <span v-if="node.aliases?.length" class="dk-aliases">
              {{ node.aliases.slice(0, 4).join(' / ') }}
            </span>
            <span class="dk-source" :title="`${node.source?.title}${node.source?.chapter ? ' · ' + node.source.chapter : ''}`">
              <BookOpen :size="13" /> {{ node.source?.title }}
              <template v-if="node.source?.chapter"> · {{ node.source.chapter }}</template>
            </span>
          </div>

          <div v-if="expanded === node.id" class="dk-detail">
            <template v-if="nodeDetail && nodeDetail.id === node.id">
              <p class="dk-detail-heading">图邻居关系（可追溯）</p>
              <ul v-if="nodeDetail.neighbors?.length" class="dk-neighbors">
                <li v-for="(nb, idx) in nodeDetail.neighbors" :key="idx">
                  <span class="dk-nb-type">{{ nb.relation_type }}</span>
                  <span class="dk-nb-dir">{{ nb.direction === 'outgoing' ? '→' : '←' }}</span>
                  <span class="dk-nb-other">{{ nb.other_id }}</span>
                  <span v-if="nb.note" class="dk-nb-note">（{{ nb.note }}）</span>
                </li>
              </ul>
              <p v-else class="dk-hint">该节点暂无图关系。</p>
            </template>
            <p v-else class="dk-hint">加载关系详情…</p>
          </div>
        </li>
      </ul>

      <ul v-if="corpusResults.length && !loading" class="dk-results dk-corpus">
        <li v-for="row in corpusResults" :key="row.reference_id || row.chunk_id" class="dk-card">
          <p class="dk-card-name">{{ row.title }}</p>
          <p class="dk-card-def">{{ row.snippet }}</p>
          <div class="dk-card-meta">
            <span class="dk-card-type">{{ row.source_kind || '语料' }}</span>
            <span v-if="row.section_path" class="dk-aliases">{{ row.section_path }}</span>
            <span v-if="(row.matched_by || []).length" class="dk-card-score">
              {{ row.matched_by.join('+') }}
            </span>
          </div>
          <div class="dk-card-meta">
            <span class="dk-source">
              <BookOpen :size="13" /> {{ row.title }}
              <template v-if="row.license"> · {{ row.license }}</template>
            </span>
            <a
              v-if="safeSourceUrl(row.source_url)"
              class="dk-source-link"
              :href="safeSourceUrl(row.source_url)"
              target="_blank"
              rel="noopener noreferrer"
            >打开出处</a>
          </div>
          <div class="dk-card-actions">
            <SfxButton variant="tertiary" size="sm" :loading="chunkLoading && expandedChunk === row.chunk_id" @click="toggleChunkDetail(row)">
              {{ expandedChunk === row.chunk_id && chunkText ? '收起原文' : '查看原文' }}
            </SfxButton>
          </div>
          <div v-if="expandedChunk === row.chunk_id" class="dk-detail">
            <p v-if="chunkLoading" class="dk-hint">原文加载中…</p>
            <p v-else-if="chunkError" class="dk-error">{{ chunkError }}</p>
            <template v-else-if="chunkText">
              <p class="dk-detail-heading">原文（{{ chunkText.char_start }}–{{ chunkText.char_end }}）</p>
              <p class="dk-chunk-text">{{ chunkText.text }}</p>
            </template>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
/* L3 内部滚动：根容器 height:100% + 内部滚动，禁止触发整页滚动 */
.dk-page {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dk-header {
  flex-shrink: 0;
  padding: var(--space-4) 20px 12px;
  border-bottom: 1px solid var(--border-default);
  background: var(--surface-page);
}

.dk-title-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 12px;
}

.dk-title {
  margin: 0;
  font-family: var(--font-sans);
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

.dk-overview {
  color: var(--text-muted);
  font-size: 13px;
}

.dk-refresh { margin-left: auto; }

.dk-search {
  display: flex;
  gap: 8px;
  align-items: center;
}

.dk-search-input-wrap {
  position: relative;
  flex: 1;
  max-width: 560px;
}

.dk-search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-muted);
}

.dk-search-input {
  width: 100%;
  padding: 8px 12px 8px 32px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: var(--surface-panel);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 14px;
}

.dk-search-input:focus {
  outline: none;
  border-color: var(--color-focus);
  box-shadow: 0 0 0 2px var(--color-brand-soft);
}

.dk-topk {
  padding: 8px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: var(--surface-panel);
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 13px;
}

.dk-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px 24px;
}

.dk-hint {
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.7;
}

.dk-error {
  color: var(--red-700, #8B3A3A);
  font-size: 14px;
}

.dk-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid var(--border-default);
  border-top-color: var(--color-focus);
  border-radius: 50%;
  vertical-align: -1px;
  animation: dk-spin 0.8s linear infinite;
}

@keyframes dk-spin { to { transform: rotate(360deg); } }

.dk-modes {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.dk-corpus-coverage { color: var(--text-secondary); }

.dk-degraded { color: var(--amber-700, #9B6618); }

.dk-release {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 12px;
}

.dk-card-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.dk-chunk-text {
  margin: 6px 0 0;
  padding: 8px 12px;
  background: var(--surface-cool);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
}

.dk-results {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dk-card {
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 12px 16px;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

/* 整卡可点：悬停给出可点击暗示，展开态高亮描边 */
.dk-card:hover {
  border-color: var(--color-focus, #355C7D);
}

.dk-card--expanded {
  border-color: var(--color-focus, #355C7D);
  box-shadow: 0 0 0 1px var(--color-brand-soft, rgba(53, 92, 125, 0.12));
}

.dk-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: none;
  background: none;
  padding: 0;
  cursor: pointer;
  text-align: left;
}

.dk-card-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.dk-card-type {
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--color-brand-soft);
  border-radius: 4px;
  padding: 1px 6px;
}

.dk-card-score {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.dk-chevron { color: var(--text-muted); }

.dk-card-def {
  margin: 8px 0 6px;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.7;
}

.dk-card-points {
  margin: 0 0 8px;
  padding-left: 18px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.7;
}

.dk-card-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
}

.dk-aliases {
  color: var(--color-brand, #14213D);
  font-family: var(--font-mono);
}

.dk-source {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-link, #355C7D);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dk-detail {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--border-default);
}

.dk-detail-heading {
  margin: 0 0 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.dk-neighbors {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--text-secondary);
}

.dk-nb-type {
  color: var(--color-brand, #14213D);
  font-family: var(--font-mono);
}

.dk-nb-dir { color: var(--text-muted); }

.dk-nb-other { font-family: var(--font-mono); }

.dk-nb-note { color: var(--text-muted); }
</style>
