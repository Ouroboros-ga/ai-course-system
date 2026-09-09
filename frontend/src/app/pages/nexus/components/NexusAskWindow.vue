<script setup>
/**
 * 询问 Nexus · 可拖动浮窗
 *
 * 它不是另一个 AI，也不是另一个会话：它就是**研究对话在工作台里多开的一个窗口**，
 * 继承同一会话上下文，因此同样能操作实验工作台（改方案走审批、取消走 cancel API）。
 *
 * 约束（v6 定版）：
 * - 引用边界由调用方决定：只传明确的 run ID / 步骤 / 有界日志片段，
 *   不复制全量日志、不混入其他会话；
 * - 拖动位置持久化到 sessionStorage，不做磁吸贴边；
 * - 关闭后实验继续运行（切回研究对话不取消实验）。
 */
import { onBeforeUnmount, ref, watch } from 'vue'
import { GripVertical, Send, X } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '询问 Nexus' },
  /** 继承的上下文说明，例如「nanoGPT 复现验证 的研究对话」 */
  contextText: { type: String, default: '' },
  /** 附加引用徽标，例如「job_xxx · step 4 · 日志末 40 行」 */
  contextPill: { type: String, default: '' },
  busy: { type: Boolean, default: false }
})

const emit = defineEmits(['close', 'send'])

const POS_KEY = 'nexus_ask_window_pos'
const draft = ref('')
const pos = ref(loadPos())
const dragging = ref(false)
let origin = null

function loadPos() {
  try {
    const raw = sessionStorage.getItem(POS_KEY)
    if (!raw) return null
    const p = JSON.parse(raw)
    return typeof p?.x === 'number' && typeof p?.y === 'number' ? p : null
  } catch {
    return null
  }
}

function savePos(p) {
  try {
    sessionStorage.setItem(POS_KEY, JSON.stringify(p))
  } catch {
    /* 存储不可用不影响拖动 */
  }
}

function onPointerDown(e) {
  if (e.button != null && e.button !== 0) return
  dragging.value = true
  origin = {
    px: e.clientX,
    py: e.clientY,
    x: pos.value?.x ?? 0,
    y: pos.value?.y ?? 0
  }
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
}

function onPointerMove(e) {
  if (!dragging.value || !origin) return
  const next = { x: origin.x + (e.clientX - origin.px), y: origin.y + (e.clientY - origin.py) }
  // 夹在视口内，允许贴边但不越界（不做磁吸）
  const maxX = window.innerWidth - 120
  const maxY = window.innerHeight - 60
  next.x = Math.min(Math.max(next.x, -(window.innerWidth - 200)), maxX)
  next.y = Math.min(Math.max(next.y, 0), maxY)
  pos.value = next
}

function onPointerUp() {
  dragging.value = false
  origin = null
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  if (pos.value) savePos(pos.value)
}

function submit() {
  const text = draft.value.trim()
  if (!text || props.busy) return
  emit('send', text)
  draft.value = ''
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submit()
  }
}

watch(
  () => props.open,
  (v) => {
    if (!v) return
    requestAnimationFrame(() => {
      const el = document.querySelector('.nxask-input')
      if (el) el.focus()
    })
  }
)

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
})
</script>

<template>
  <div
    v-if="open"
    class="nxask"
    :style="pos ? { transform: `translate(${pos.x}px, ${pos.y}px)` } : null"
    role="dialog"
    :aria-label="title"
  >
    <header class="nxask-bar" @pointerdown="onPointerDown">
      <GripVertical :size="14" class="nxask-grip" />
      <b>{{ title }}</b>
      <span class="nxask-sp" />
      <span class="nxask-hint">按住此处拖动</span>
      <SfxButton variant="tertiary" size="sm" title="关闭（实验继续运行）" @click="emit('close')">
        <template #icon><X :size="13" /></template>
      </SfxButton>
    </header>

    <div v-if="contextText" class="nxask-ctx">
      继承：<b>{{ contextText }}</b>
      <span v-if="contextPill" class="nxask-pill">{{ contextPill }}</span>
    </div>

    <div class="nxask-body">
      <slot />
      <p v-if="!$slots.default" class="nxask-empty">
        这里复用同一会话的研究对话。提问会带上上面的明确引用，回答不会脱离本会话上下文。
      </p>
    </div>

    <footer class="nxask-foot">
      <textarea
        v-model="draft"
        class="nxask-input"
        rows="2"
        :disabled="busy"
        placeholder="继续问，或让它调整方案 / 取消本次运行…"
        @keydown="onKeydown"
      />
      <div class="nxask-actions">
        <span class="nxask-note">Enter 发送 · Shift+Enter 换行</span>
        <span class="nxask-sp" />
        <SfxButton variant="primary" size="sm" :disabled="!draft.trim() || busy" @click="submit">
          <template #icon><Send :size="13" /></template>
          发送
        </SfxButton>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.nxask {
  /* fixed：浮窗属于视口，不属于任何列——拖动后不随主区滚动/切换而跳位。 */
  position: fixed;
  top: 96px;
  /* 默认让开右侧 48px 图标轨 + 320px 抽屉，避免一打开就压住抽屉内容；
     用户拖动后的位置存 sessionStorage，之后以用户位置为准。 */
  right: 400px;
  width: 396px;
  max-width: calc(100vw - 48px);
  background: var(--surface-panel);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  /* 高于抽屉/浮层（页面内最高 60），它是用户自己摆位的对话框，不该被别的面板盖住 */
  z-index: 70;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.nxask-bar {
  display: flex; align-items: center; gap: var(--space-2);
  height: 36px; padding: 0 var(--space-2) 0 var(--space-3);
  background: var(--surface-soft); border-bottom: 1px solid var(--border-default);
  cursor: grab; user-select: none;
}
.nxask-bar:active { cursor: grabbing; }
.nxask-bar b { font-size: var(--ui-sm-size); font-weight: 600; }
.nxask-grip { color: var(--text-disabled); }
.nxask-hint { font-size: 10px; color: var(--text-disabled); }
.nxask-sp { flex: 1; }
.nxask-ctx {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin: var(--space-2) var(--space-3) 0; padding: 5px 8px;
  background: var(--surface-soft); border: 1px solid var(--border-default);
  border-radius: var(--radius-xs); font-size: var(--caption-size); color: var(--text-muted);
}
.nxask-ctx b { font-weight: 500; color: var(--text-secondary); }
.nxask-pill {
  font-family: var(--font-mono); font-size: 10px; color: var(--nexus-accent);
  background: var(--nexus-accent-soft); border: 1px solid var(--nexus-accent-line);
  border-radius: 2px; padding: 0 4px;
}
.nxask-body { padding: var(--space-3); max-height: 320px; overflow-y: auto; }
.nxask-empty { font-size: var(--ui-sm-size); line-height: 1.7; color: var(--text-muted); margin: 0; }
.nxask-foot { border-top: 1px solid var(--border-default); padding: var(--space-2) var(--space-3) var(--space-3); background: var(--surface-soft); }
.nxask-input {
  width: 100%; resize: none; border: 1px solid var(--border-default);
  border-radius: var(--radius-xs); background: var(--surface-panel);
  padding: 6px 8px; font-family: inherit; font-size: var(--ui-sm-size);
  color: var(--text-primary); line-height: 1.6;
}
.nxask-input:focus { outline: 2px solid var(--color-focus); outline-offset: 1px; }
.nxask-actions { display: flex; align-items: center; margin-top: var(--space-2); }
.nxask-note { font-size: 10px; color: var(--text-disabled); }
</style>
