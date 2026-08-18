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
})

const expandedCases = ref(new Set())

const passedCount = computed(() => {
  return props.testCases.filter(tc => tc.passed).length
})

const totalCount = computed(() => props.testCases.length)

const passRate = computed(() => {
  if (!totalCount.value) return 0
  return Math.round((passedCount.value / totalCount.value) * 100)
})

const outcomeConfig = computed(() => {
  const configs = {
    accepted: { label: '全部通过', color: 'var(--green-500)', icon: CheckCircle },
    wrong_answer: { label: '答案错误', color: 'var(--red-500)', icon: XCircle },
    time_limit_exceeded: { label: '时间超限', color: 'var(--amber-500)', icon: Clock },
    memory_limit_exceeded: { label: '内存超限', color: 'var(--amber-500)', icon: AlertTriangle },
    runtime_error: { label: '运行时错误', color: 'var(--red-500)', icon: XCircle },
    compile_error: { label: '编译错误', color: 'var(--red-500)', icon: XCircle },
    cancelled: { label: '已取消', color: 'var(--code-muted)', icon: XCircle },
    sandbox_unavailable: { label: '沙箱不可用', color: 'var(--amber-500)', icon: AlertTriangle },
  }
  return configs[props.outcome] || null
})

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

    <!-- 测试用例列表 -->
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
  background: rgba(255, 255, 255, 0.03);
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
  background: rgba(0, 0, 0, 0.1);
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
}

.detail-pre.is-wrong {
  border-color: rgba(184, 92, 92, 0.5);
  background: rgba(184, 92, 92, 0.08);
}

.detail-pre.is-error {
  border-color: rgba(184, 92, 92, 0.5);
  background: rgba(184, 92, 92, 0.08);
  color: #F08080;
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
