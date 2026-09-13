<script setup>
import { computed, ref } from 'vue'
import { CheckCircle, XCircle, ChevronDown, ChevronRight, Lock, LoaderCircle, Clock, AlertTriangle } from 'lucide-vue-next'

const props = defineProps({
  testCases: {
    type: Array,
    default: () => [],
    // 每个用例: { case_name, passed, is_hidden, stdin?, expected_stdout?, actual_stdout?, time_ms?, memory_kb?, reason? }
  },
  outcome: { type: String, default: '' },
  status: {
    type: String,
    default: 'idle',
    validator: (v) => ['idle', 'running', 'done'].includes(v),
  },
  progress: { type: Number, default: 0 }, // 0-100
  // 正式评测汇总（洛谷式判题结果的右栏）：
  // { outcome, score, timeMs, memoryKb, language, passedCount, totalCount, compileMessage, runtimeMessage, errorMessage, submittedAt }
  summary: { type: Object, default: null },
})

const expandedCases = ref(new Set())

const passedCount = computed(() => {
  return props.testCases.filter(tc => tc.passed).length
})

const totalCount = computed(() => props.testCases.length)

const outcomeConfig = computed(() => {
  const configs = {
    accepted: { label: '全部通过', short: 'AC', color: 'var(--green-600, #3F8F4A)', icon: CheckCircle },
    wrong_answer: { label: '答案错误', short: 'WA', color: 'var(--red-600, #C04646)', icon: XCircle },
    time_limit_exceeded: { label: '时间超限', short: 'TLE', color: 'var(--amber-600, #B5892B)', icon: Clock },
    memory_limit_exceeded: { label: '内存超限', short: 'MLE', color: 'var(--amber-600, #B5892B)', icon: AlertTriangle },
    runtime_error: { label: '运行时错误', short: 'RE', color: 'var(--red-600, #C04646)', icon: XCircle },
    compile_error: { label: '编译错误', short: 'CE', color: 'var(--red-600, #C04646)', icon: XCircle },
    cancelled: { label: '已取消', short: '—', color: 'var(--code-muted)', icon: XCircle },
    sandbox_unavailable: { label: '沙箱不可用', short: '—', color: 'var(--amber-600, #B5892B)', icon: AlertTriangle },
  }
  return configs[props.outcome] || null
})

/** 逐用例的短判定。通过 = AC；失败沿用整次评测的失败模式
 *  （后端逐用例只有 passed + reason，失败模式是 run 级别的事实，
 *  硬编 WA 会把 TLE 谎报成答案错误）。 */
function shortVerdict(tc) {
  if (tc.passed) return 'AC'
  return outcomeConfig.value?.short || 'WA'
}

/** 用例块的配色：AC 绿 / 失败按模式 / 隐藏用例灰 */
function tileTone(tc) {
  if (tc.is_hidden) return 'tone-muted'
  if (tc.passed) return 'tone-pass'
  const short = shortVerdict(tc)
  if (short === 'TLE' || short === 'MLE') return 'tone-warn'
  return 'tone-fail'
}

function toggleCase(index) {
  const tc = props.testCases[index]
  if (tc?.is_hidden) return // 隐藏测试用例不可展开
  const key = String(index)
  if (expandedCases.value.has(key)) {
    expandedCases.value.delete(key)
  } else {
    expandedCases.value.add(key)
  }
}

function isExpanded(index) {
  return expandedCases.value.has(String(index))
}

function formatTime(ms) {
  if (!ms) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function formatMemory(kb) {
  if (!kb) return '—'
  if (kb < 1024) return `${kb}KB`
  return `${(kb / 1024).toFixed(1)}MB`
}

function formatScore(score) {
  if (score === null || score === undefined) return '—'
  const n = Number(score)
  if (!Number.isFinite(n)) return String(score)
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}
</script>

<template>
  <div class="code-testcases">
    <!-- 顶部概览 -->
    <div class="testcases-header">
      <div class="header-left">
        <span class="header-title">测试用例</span>
        <span v-if="status === 'running'" class="header-progress">
          <LoaderCircle :size="14" class="spinner" />
          评测中 {{ progress }}%
        </span>
        <span v-else-if="totalCount > 0" class="header-count">
          {{ passedCount }} / {{ totalCount }} 通过
        </span>
      </div>
      <div v-if="outcomeConfig" class="header-outcome" :style="{ color: outcomeConfig.color }">
        <component :is="outcomeConfig.icon" :size="16" />
        <span>{{ outcomeConfig.label }}</span>
      </div>
    </div>

    <!-- 进度条 -->
    <div v-if="status === 'running'" class="progress-bar">
      <div class="progress-fill" :style="{ width: `${progress}%` }"></div>
    </div>

    <!-- 判题结果横幅（洛谷式：状态 + 分数 + 用时/内存/语言） -->
    <div v-if="summary && status === 'done'" class="verdict-banner" :class="outcomeConfig ? 'has-outcome' : ''">
      <div class="verdict-main" :style="{ color: outcomeConfig?.color || 'var(--code-text)' }">
        <component :is="outcomeConfig?.icon || CheckCircle" :size="22" />
        <span class="verdict-label">{{ outcomeConfig?.label || '评测完成' }}</span>
      </div>
      <div class="verdict-facts">
        <div class="fact">
          <span class="fact-label">评测分数</span>
          <span class="fact-value is-score">{{ formatScore(summary.score) }}</span>
        </div>
        <div class="fact">
          <span class="fact-label">用时</span>
          <span class="fact-value">{{ formatTime(summary.timeMs) }}</span>
        </div>
        <div class="fact">
          <span class="fact-label">内存</span>
          <span class="fact-value">{{ formatMemory(summary.memoryKb) }}</span>
        </div>
        <div class="fact">
          <span class="fact-label">语言</span>
          <span class="fact-value">{{ summary.language || '—' }}</span>
        </div>
      </div>
    </div>

    <!-- 编译 / 运行错误原文（CE/RE 时一行报错不够，给全文） -->
    <div
      v-if="summary && status === 'done' && (summary.compileMessage || summary.runtimeMessage)"
      class="message-block"
    >
      <div class="detail-label">{{ summary.compileMessage ? '编译输出' : '运行输出' }}</div>
      <pre class="detail-pre is-error">{{ summary.compileMessage || summary.runtimeMessage }}</pre>
    </div>

    <!-- 测试点卡片（洛谷式 tile 网格，点一下展开下方明细） -->
    <div class="testcase-tiles" v-if="testCases.length">
      <button
        v-for="(tc, index) in testCases"
        :key="index"
        type="button"
        class="tile"
        :class="[tileTone(tc), { 'is-expanded': isExpanded(index) && !tc.is_hidden }]"
        :disabled="tc.is_hidden"
        :title="tc.is_hidden ? '隐藏测试点（不可查看明细）' : `${shortVerdict(tc)} · 点击查看明细`"
        @click="toggleCase(index)"
      >
        <span class="tile-index">#{{ index + 1 }}</span>
        <span class="tile-verdict">{{ tc.is_hidden ? '🔒' : shortVerdict(tc) }}</span>
        <span class="tile-meta">
          {{ formatTime(tc.time_ms) }} / {{ formatMemory(tc.memory_kb) }}
        </span>
      </button>
    </div>

    <!-- 测试用例明细列表 -->
    <div class="testcases-list" v-if="testCases.length">
      <div
        v-for="(tc, index) in testCases"
        :key="index"
        class="testcase-item"
        :class="{
          'is-passed': tc.passed,
          'is-failed': !tc.passed,
          'is-hidden': tc.is_hidden,
          'is-expanded': isExpanded(index),
        }"
      >
        <div class="testcase-header" @click="toggleCase(index)">
          <div class="testcase-status">
            <component
              v-if="tc.is_hidden"
              :is="Lock"
              :size="14"
              class="status-icon is-hidden"
            />
            <component
              v-else-if="tc.passed"
              :is="CheckCircle"
              :size="14"
              class="status-icon is-passed"
            />
            <component
              v-else
              :is="XCircle"
              :size="14"
              class="status-icon is-failed"
            />
            <span class="testcase-name">
              {{ tc.is_hidden ? '隐藏测试' : tc.case_name || `测试用例 ${index + 1}` }}
            </span>
          </div>
          <div class="testcase-meta">
            <span class="meta-verdict">{{ shortVerdict(tc) }}</span>
            <span v-if="tc.time_ms !== undefined" class="meta-time">{{ formatTime(tc.time_ms) }}</span>
            <component
              v-if="!tc.is_hidden"
              :is="isExpanded(index) ? ChevronDown : ChevronRight"
              :size="14"
              class="expand-icon"
            />
          </div>
        </div>

        <!-- 展开详情 -->
        <div v-if="isExpanded(index) && !tc.is_hidden" class="testcase-detail">
          <div v-if="tc.stdin" class="detail-section">
            <div class="detail-label">输入</div>
            <pre class="detail-pre">{{ tc.stdin }}</pre>
          </div>
          <div v-if="tc.expected_stdout" class="detail-section">
            <div class="detail-label">期望输出</div>
            <pre class="detail-pre">{{ tc.expected_stdout }}</pre>
          </div>
          <div v-if="tc.actual_stdout" class="detail-section">
            <div class="detail-label">实际输出</div>
            <pre class="detail-pre is-wrong" v-if="!tc.passed">{{ tc.actual_stdout }}</pre>
            <pre class="detail-pre" v-else>{{ tc.actual_stdout }}</pre>
          </div>
          <div v-if="tc.reason && !tc.passed" class="detail-section">
            <div class="detail-label">错误信息</div>
            <pre class="detail-pre is-error">{{ tc.reason }}</pre>
          </div>
          <div class="detail-meta">
            <span>时间: {{ formatTime(tc.time_ms) }}</span>
            <span v-if="tc.memory_kb">内存: {{ formatMemory(tc.memory_kb) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else-if="status === 'idle'" class="testcases-empty">
      <CheckCircle :size="32" :stroke-width="1.5" />
      <p>提交评测后，测试结果将显示在这里</p>
    </div>
  </div>
</template>

<style scoped>
.code-testcases {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--code-panel);
  color: var(--code-text);
  font-size: 13px;
}

.testcases-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 1px solid var(--code-border);
  background: rgba(0, 0, 0, 0.15);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--code-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.header-count {
  font-size: 12px;
  color: var(--code-muted);
  font-family: var(--font-mono);
}

.header-progress {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ink-300);
  font-family: var(--font-mono);
}

.header-progress .spinner {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.header-outcome {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
}

.progress-bar {
  flex-shrink: 0;
  height: 2px;
  background: var(--code-border);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--ink-500);
  transition: width 0.3s ease;
}

/* ── 判题结果横幅（洛谷式） ─────────────────────────────── */
.verdict-banner {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px 18px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--code-border);
}

.verdict-main {
  display: flex;
  align-items: center;
  gap: 8px;
}

.verdict-label {
  font-size: 18px;
  font-weight: 650;
  letter-spacing: 0.02em;
}

.verdict-facts {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 20px;
}

.fact {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.fact-label {
  font-size: 11px;
  color: var(--code-muted);
  letter-spacing: 0.04em;
}

.fact-value {
  font-size: 14px;
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--code-text);
}

.fact-value.is-score {
  font-size: 16px;
  color: var(--ink-900, var(--code-text));
}

/* ── 测试点卡片网格 ─────────────────────────────────────── */
.testcase-tiles {
  flex-shrink: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(88px, 1fr));
  gap: 6px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--code-border);
}

.tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  padding: 7px 4px 6px;
  border: 1px solid transparent;
  border-radius: 6px;
  color: #fff;
  font-family: var(--font-mono);
  cursor: pointer;
  transition: transform var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast) var(--ease-out);
}

.tile:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 3px 10px rgba(16, 24, 32, 0.18);
}

.tile:disabled { cursor: default; opacity: 0.75; }

.tile.is-expanded { outline: 2px solid var(--ink-900, #24292F); outline-offset: 1px; }

.tile.tone-pass { background: var(--green-500, #4C9A54); }
.tile.tone-fail { background: var(--red-500, #C25B5B); }
.tile.tone-warn { background: var(--amber-500, #C99A3C); }
.tile.tone-muted { background: var(--code-muted); }

.tile-index {
  font-size: 10px;
  opacity: 0.85;
  line-height: 1.2;
}

.tile-verdict {
  font-size: 14px;
  font-weight: 700;
  line-height: 1.4;
  letter-spacing: 0.04em;
}

.tile-meta {
  font-size: 9.5px;
  opacity: 0.9;
  line-height: 1.3;
  white-space: nowrap;
}

.message-block {
  flex-shrink: 0;
  padding: 10px 16px;
  border-bottom: 1px solid var(--code-border);
}

.testcases-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.testcase-item {
  border: 1px solid var(--code-border);
  border-radius: 6px;
  overflow: hidden;
  transition: border-color var(--duration-fast) var(--ease-out);
}

.testcase-item.is-passed {
  border-color: rgba(94, 140, 97, 0.4);
}

.testcase-item.is-failed {
  border-color: rgba(184, 92, 92, 0.4);
}

.testcase-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}

.testcase-header:hover {
  background: rgba(127, 127, 127, 0.08);
}

.testcase-item.is-hidden .testcase-header {
  cursor: default;
}

.testcase-status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-icon {
  flex-shrink: 0;
}

.status-icon.is-passed {
  color: var(--green-500);
}

.status-icon.is-failed {
  color: var(--red-500);
}

.status-icon.is-hidden {
  color: var(--code-muted);
}

.testcase-name {
  font-size: 13px;
  font-weight: 500;
  font-family: var(--font-mono);
}

.testcase-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}

.meta-verdict {
  font-size: 11px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--code-muted);
}

.meta-time {
  font-size: 11px;
  color: var(--code-muted);
  font-family: var(--font-mono);
}

.expand-icon {
  color: var(--code-muted);
  transition: transform var(--duration-fast) var(--ease-out);
}

.testcase-detail {
  padding: 0 12px 12px;
  border-top: 1px solid var(--code-border);
  background: rgba(127, 127, 127, 0.06);
}

.detail-section {
  margin-top: 10px;
}

.detail-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--code-muted);
  margin-bottom: 4px;
}

.detail-pre {
  margin: 0;
  padding: 8px 10px;
  background: var(--code-bg);
  border: 1px solid var(--code-border);
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
  color: var(--code-text);
  max-height: 220px;
  overflow: auto;
}

.detail-pre.is-wrong {
  border-color: rgba(184, 92, 92, 0.5);
  background: rgba(184, 92, 92, 0.08);
}

.detail-pre.is-error {
  border-color: rgba(184, 92, 92, 0.5);
  background: rgba(184, 92, 92, 0.08);
  color: #C25B5B;
}

.detail-meta {
  display: flex;
  gap: 16px;
  margin-top: 10px;
  font-size: 11px;
  color: var(--code-muted);
  font-family: var(--font-mono);
}

.testcases-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--code-muted);
  gap: 8px;
}

.testcases-empty p {
  margin: 0;
  font-size: 13px;
}
</style>
