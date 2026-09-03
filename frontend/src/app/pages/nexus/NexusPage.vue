<script setup>
/**
 * Nexus AI 全局入口（CodeNexus 转型 S1 双轨期）。
 *
 * 数据源：POST /api/v1/nexus/chat/stream（后端反代 → 独立进程 Nexus Runtime）。
 * 与课程内 TeachingAgent 的分工见 docs/phase1/2026-09-03_CodeNexus转型实施决策.md D2：
 * TeachingAgent 是课程内固定工作流的问答，Nexus 负责复杂问题拆解与持续执行，
 * 因此本页要把「过程」显性化——工具调用与结果和最终答复同等重要。
 *
 * 设计遵循 design.md：三层滚动（本页 L3，根容器 height:100% + 内部滚动）、
 * 语义令牌（--color-brand / --surface-panel / --border-default 等）、SfxButton 规范。
 *
 * P0 限制（诚实呈现，不掩盖）：会话状态存在 Runtime 进程内存（InMemorySaver），
 * 服务重启即清空；失败一律显示真实错误码，不退化成"看起来正常"的空回答。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { AlertTriangle, ChevronDown, ChevronRight, Send, Square, Wrench } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'
import { getNexusHealth, streamNexusMessage } from '@/api/nexus.js'

/** 单条 turn：一次用户输入 + 本轮产生的工具事件与答复。 */
const turns = ref([])
const draft = ref('')
const streaming = ref(false)
const error = ref('')
const health = ref(null)
const healthError = ref('')
const scrollArea = ref(null)
const expandedTools = ref(new Set())

let controller = null
// 会话 ID 在页面生命周期内固定：Runtime 侧据此续聊（用例 6）。
const sessionId = `web-${Math.random().toString(36).slice(2, 10)}`

const canSend = computed(() => draft.value.trim().length > 0 && !streaming.value)

const runtimeReady = computed(() => health.value?.status === 'ok')
const llmConfigured = computed(() => health.value?.llm_configured === true)

/** 健康探测只用于给出准确的前置提示，不阻塞输入。 */
async function loadHealth() {
  try {
    health.value = await getNexusHealth()
    healthError.value = ''
  } catch (err) {
    health.value = null
    healthError.value = err?.errorCode || err?.message || 'Nexus 运行时不可达'
  }
}

async function scrollToBottom() {
  await nextTick()
  const el = scrollArea.value
  if (el) el.scrollTop = el.scrollHeight
}

function toolKey(turnIndex, eventIndex) {
  return `${turnIndex}:${eventIndex}`
}

function isToolExpanded(turnIndex, eventIndex) {
  return expandedTools.value.has(toolKey(turnIndex, eventIndex))
}

function toggleTool(turnIndex, eventIndex) {
  const key = toolKey(turnIndex, eventIndex)
  const next = new Set(expandedTools.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedTools.value = next
}

function formatArgs(args) {
  if (args === null || args === undefined) return ''
  if (typeof args === 'string') return args
  try {
    return JSON.stringify(args, null, 2)
  } catch {
    return String(args)
  }
}

function handleEvent(turn, { event, data }) {
  if (event === 'token') {
    turn.answer += data?.content ?? ''
  } else if (event === 'tool_call') {
    turn.toolEvents.push({
      kind: 'call',
      name: data?.name || '未知工具',
      args: data?.args,
    })
  } else if (event === 'tool_result') {
    turn.toolEvents.push({
      kind: 'result',
      name: data?.name || '未知工具',
      status: data?.status || 'success',
      content: data?.content ?? '',
    })
  } else if (event === 'done') {
    turn.tokenCount = data?.token_count ?? null
  }
  scrollToBottom()
}

async function send() {
  const message = draft.value.trim()
  if (!message || streaming.value) return

  const turn = {
    question: message,
    answer: '',
    toolEvents: [],
    tokenCount: null,
    failure: '',
  }
  turns.value.push(turn)
  draft.value = ''
  error.value = ''
  streaming.value = true
  controller = new AbortController()
  scrollToBottom()

  try {
    await streamNexusMessage({
      message,
      sessionId,
      signal: controller.signal,
      onEvent: (evt) => handleEvent(turn, evt),
    })
  } catch (err) {
    if (err?.name === 'AbortError') {
      turn.failure = '已中止本次回答'
    } else {
      // 把真实错误码呈现在这一轮里：不是空回答，也不是通用"网络异常"。
      const code = err?.errorCode ? `${err.errorCode}：` : ''
      turn.failure = `${code}${err?.message || '请求失败'}`
      error.value = turn.failure
    }
  } finally {
    streaming.value = false
    controller = null
    scrollToBottom()
  }
}

function stop() {
  if (controller) controller.abort()
}

onMounted(loadHealth)
onBeforeUnmount(() => {
  if (controller) controller.abort()
})
</script>

<template>
  <div class="nx-page">
    <header class="nx-header">
      <div class="nx-title-row">
        <h1 class="nx-title">Nexus AI</h1>
        <span class="nx-subtitle">复杂问题拆解 · 论文研究 · 快速复现</span>
      </div>

      <div v-if="healthError" class="nx-status is-error">
        <AlertTriangle :size="14" />
        <span>Nexus 运行时不可达（{{ healthError }}）——尚未部署或已停止，对话将失败而不会给出编造答复。</span>
      </div>
      <div v-else-if="health && !llmConfigured" class="nx-status is-warn">
        <AlertTriangle :size="14" />
        <span>Nexus 运行时在线，但 LLM 未配置，对话会返回 LLM_NOT_CONFIGURED。</span>
      </div>
      <div v-else-if="runtimeReady" class="nx-status">
        <span>运行时在线</span>
        <span class="nx-dot">·</span>
        <span>Web 搜索：{{ health.searxng_configured ? 'SearXNG 主通道' : (health.ddgs_enabled ? '本机降级通道' : '未配置') }}</span>
        <span class="nx-dot">·</span>
        <span>复现执行：{{ health.repro_worker_configured ? '已接入' : '未接入' }}</span>
      </div>
    </header>

    <div ref="scrollArea" class="nx-scroll">
      <p v-if="!turns.length" class="nx-hint">
        试一试：「搜索 Transformer 模型的最新进展」「搜索 arXiv 上关于 GPT-2 的论文」
        「帮我规划 nanoGPT 的复现步骤」。当前会话仅保留至运行时重启。
      </p>

      <article v-for="(turn, turnIndex) in turns" :key="turnIndex" class="nx-turn">
        <div class="nx-bubble is-user">{{ turn.question }}</div>

        <ol v-if="turn.toolEvents.length" class="nx-tools">
          <li
            v-for="(evt, eventIndex) in turn.toolEvents"
            :key="eventIndex"
            class="nx-tool"
            :class="{ 'is-failed': evt.kind === 'result' && evt.status !== 'success' }"
          >
            <SfxButton
              variant="tertiary"
              size="sm"
              class="nx-tool-toggle"
              @click="toggleTool(turnIndex, eventIndex)"
            >
              <template #icon>
                <component
                  :is="isToolExpanded(turnIndex, eventIndex) ? ChevronDown : ChevronRight"
                  :size="14"
                />
              </template>
              <span class="nx-tool-summary">
                <Wrench :size="13" class="nx-tool-icon" />
                {{ evt.kind === 'call' ? '调用' : '返回' }} {{ evt.name }}
                <span v-if="evt.kind === 'result'" class="nx-tool-status">{{ evt.status }}</span>
              </span>
            </SfxButton>
            <pre v-if="isToolExpanded(turnIndex, eventIndex)" class="nx-tool-detail">{{
              evt.kind === 'call' ? formatArgs(evt.args) : evt.content
            }}</pre>
          </li>
        </ol>

        <div v-if="turn.answer" class="nx-bubble is-agent">{{ turn.answer }}</div>

        <div v-if="turn.failure" class="nx-turn-error">
          <AlertTriangle :size="14" />
          <span>{{ turn.failure }}</span>
        </div>

        <p v-else-if="!turn.answer && !streaming && !turn.toolEvents.length" class="nx-turn-empty">
          运行时未返回任何内容（既无工具调用也无答复）。
        </p>
      </article>
    </div>

    <footer class="nx-composer">
      <textarea
        v-model="draft"
        class="nx-input"
        rows="2"
        placeholder="描述一个需要拆解的问题…（Enter 发送，Shift+Enter 换行）"
        :disabled="streaming"
        @keydown.enter.exact.prevent="send"
      />
      <div class="nx-actions">
        <SfxButton v-if="streaming" variant="secondary" @click="stop">
          <template #icon><Square :size="15" /></template>
          中止
        </SfxButton>
        <SfxButton v-else variant="primary" :disabled="!canSend" @click="send">
          <template #icon><Send :size="15" /></template>
          发送
        </SfxButton>
      </div>
    </footer>
  </div>
</template>

<style scoped>
/* L3 内部滚动：根容器 height:100% + 内部滚动，禁止触发整页滚动 */
.nx-page {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.nx-header {
  flex-shrink: 0;
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--border-subtle);
}

.nx-title-row {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.nx-title {
  margin: 0;
  font-size: var(--title-2-size);
  font-weight: var(--title-2-weight);
  color: var(--text-primary);
}

.nx-subtitle {
  font-size: var(--caption-size);
  color: var(--text-muted);
}

.nx-status {
  margin-top: var(--space-2);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--caption-size);
  color: var(--text-secondary);
}

.nx-status.is-error {
  color: var(--red-700);
}

.nx-status.is-warn {
  color: var(--amber-700);
}

.nx-dot {
  color: var(--text-disabled);
}

.nx-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px 24px;
}

.nx-hint {
  margin: 0;
  font-size: var(--body-md-size);
  color: var(--text-muted);
  line-height: 1.7;
}

.nx-turn {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-6);
}

.nx-bubble {
  padding: 10px 14px;
  border-radius: var(--radius-md);
  font-size: var(--body-md-size);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.nx-bubble.is-user {
  align-self: flex-end;
  max-width: 78%;
  background: var(--color-brand-soft);
  color: var(--text-primary);
}

.nx-bubble.is-agent {
  background: var(--surface-panel);
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
}

.nx-tools {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.nx-tool {
  border-left: 2px solid var(--border-default);
  padding-left: var(--space-2);
}

.nx-tool.is-failed {
  border-left-color: var(--red-500);
}

.nx-tool-toggle {
  justify-content: flex-start;
}

.nx-tool-summary {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
}

.nx-tool-icon {
  color: var(--text-muted);
}

.nx-tool-status {
  color: var(--text-muted);
}

.nx-tool-detail {
  margin: var(--space-1) 0 var(--space-2);
  padding: 10px 12px;
  background: var(--code-bg);
  border: 1px solid var(--code-border);
  border-radius: var(--radius-sm);
  color: var(--code-text);
  font-family: var(--font-mono);
  font-size: var(--caption-size);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 260px;
  overflow: auto;
}

.nx-turn-error {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--caption-size);
  color: var(--red-700);
}

.nx-turn-empty {
  margin: 0;
  font-size: var(--caption-size);
  color: var(--text-muted);
}

.nx-composer {
  flex-shrink: 0;
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
  padding: 12px 20px 16px;
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-page);
}

.nx-input {
  flex: 1;
  min-width: 0;
  resize: none;
  padding: 10px 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-panel);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--body-md-size);
  line-height: 1.6;
}

.nx-input:focus {
  outline: 2px solid var(--color-focus);
  outline-offset: 1px;
  border-color: var(--color-brand);
}

.nx-actions {
  flex-shrink: 0;
}
</style>
