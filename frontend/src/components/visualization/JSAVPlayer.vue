<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import {
  Play, Pause, SkipBack, SkipForward, RotateCcw,
  Link2, Info, AlertCircle, Code,
} from 'lucide-vue-next'

const props = defineProps({
  planData: { type: Object, required: true },
  autoplay: { type: Boolean, default: false },
})

const emit = defineEmits(['return-anchor', 'ready', 'error'])

/* ── 算法白名单（与后端 algorithm_registry 一致）── */
const ALGORITHM_WHITELIST = new Set([
  'binary_search', 'bubble_sort', 'selection_sort', 'insertion_sort', 'quick_sort',
  'stack_operations', 'queue_operations',
  'factorial_recursion', 'fibonacci_recursion',
  'tree_traversal', 'graph_bfs', 'graph_dfs',
])

/* ── 支持 JSAV 数组渲染的算法类别 ── */
const JSAV_ARRAY_CATEGORIES = new Set(['binary', 'sorting'])

/* ── JSAV CDN（按需加载，不打包到主应用）── */
const JSAV_DEPS = [
  'https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js',
  'https://cdn.jsdelivr.net/npm/raphael@2.3.0/raphael.min.js',
  'https://cdn.jsdelivr.net/npm/jsav@0.4.1/build/JSAV.js',
]
const JSAV_CSS_URL = 'https://cdn.jsdelivr.net/npm/jsav@0.4.1/build/JSAV.css'
const JSAV_LOAD_TIMEOUT = 12000

/* ── 响应式状态 ── */
const loadState = ref('loading') // 'loading' | 'loaded' | 'failed'
const loadError = ref('')
const jsavActive = ref(false)
const currentStep = ref(0)
const isPlaying = ref(false)
const jsavContainerRef = ref(null)

let jsavInstance = null
let jsavArray = null
let playTimer = null

/* ── 计划数据提取（兼容完整序列化计划和 plan_data 对象）── */
const plan = computed(() => {
  const d = props.planData
  return d?.plan_data ?? d ?? {}
})

const algorithmId = computed(() => plan.value.algorithm_id || '')
const algorithmName = computed(() =>
  plan.value.algorithm_name || props.planData?.algorithm_name || algorithmId.value,
)
const algorithmCategory = computed(() => plan.value.algorithm_category || '')
const initialParams = computed(() => plan.value.initial_params || {})
const steps = computed(() => plan.value.steps || [])
const highlights = computed(() => plan.value.highlights || [])
const playbackSpeed = computed(() => plan.value.playback_speed || 1.0)
const returnAnchor = computed(() =>
  props.planData?.return_anchor || plan.value.return_anchor || null,
)

const isWhitelisted = computed(() => ALGORITHM_WHITELIST.has(algorithmId.value))
const canUseJSAV = computed(() =>
  isWhitelisted.value && JSAV_ARRAY_CATEGORIES.has(algorithmCategory.value),
)
const showFallback = computed(() => !jsavActive.value && loadState.value !== 'loading')
const showWhitelistWarning = computed(() => !isWhitelisted.value)

/* currentStep 0 = 初始状态, 1..N = 对应 steps[0..N-1] */
const totalSteps = computed(() => steps.value.length)
const stepDescription = computed(() => {
  if (totalSteps.value === 0) return '无可视化步骤'
  if (currentStep.value === 0) return '初始状态'
  const step = steps.value[currentStep.value - 1]
  return step?.description || `步骤 ${currentStep.value}`
})
const progressPercent = computed(() => {
  if (totalSteps.value === 0) return 0
  return (currentStep.value / totalSteps.value) * 100
})
const canNext = computed(() => currentStep.value < totalSteps.value)
const canPrev = computed(() => currentStep.value > 0)

const displayParams = computed(() => {
  const params = initialParams.value
  const result = {}
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      result[key] = `[${value.join(', ')}]`
    } else if (typeof value === 'object' && value !== null) {
      result[key] = JSON.stringify(value)
    } else {
      result[key] = String(value)
    }
  }
  return result
})
const hasParams = computed(() => Object.keys(displayParams.value).length > 0)

/* ════════════════════════════════════════════
   动态脚本 / 样式加载
   ════════════════════════════════════════════ */

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[data-jsav-src="${src}"]`)
    if (existing) {
      if (existing.dataset.loaded === 'true') return resolve()
      existing.addEventListener('load', () => resolve())
      existing.addEventListener('error', () => reject(new Error(`加载失败: ${src}`)))
      return
    }
    const script = document.createElement('script')
    script.src = src
    script.async = true
    script.dataset.jsavSrc = src
    script.onload = () => {
      script.dataset.loaded = 'true'
      resolve()
    }
    script.onerror = () => reject(new Error(`加载失败: ${src}`))
    document.head.appendChild(script)
  })
}

function loadStylesheet(href) {
  return new Promise((resolve) => {
    if (document.querySelector(`link[data-jsav-href="${href}"]`)) return resolve()
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = href
    link.dataset.jsavHref = href
    link.onload = () => resolve()
    link.onerror = () => resolve() // CSS 加载失败不阻断主流程
    document.head.appendChild(link)
  })
}

async function loadJSAV() {
  loadState.value = 'loading'
  try {
    loadStylesheet(JSAV_CSS_URL)

    const loadPromise = (async () => {
      for (const src of JSAV_DEPS) {
        await loadScript(src)
      }
    })()

    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(() => reject(new Error('JSAV 加载超时')), JSAV_LOAD_TIMEOUT),
    )

    await Promise.race([loadPromise, timeoutPromise])

    if (typeof window.JSAV !== 'function') {
      throw new Error('JSAV 库未正确初始化')
    }

    loadState.value = 'loaded'
    emit('ready')
  } catch (err) {
    loadState.value = 'failed'
    loadError.value = err?.message || 'JSAV 加载失败'
    emit('error', loadError.value)
  }
}

/* ════════════════════════════════════════════
   JSAV 可视化构建
   ════════════════════════════════════════════ */

function buildHighlightsMap() {
  const map = new Map()
  for (const h of highlights.value) {
    if (h && typeof h.step === 'number') {
      const arr = map.get(h.step) || []
      arr.push(h)
      map.set(h.step, arr)
    }
  }
  return map
}

function buildVisualization() {
  if (!jsavContainerRef.value || typeof window.JSAV !== 'function') return

  try {
    jsavContainerRef.value.innerHTML = ''

    const container = jsavContainerRef.value
    const av = new window.JSAV(container)
    jsavInstance = av

    const arrayData = initialParams.value.array || []
    if (!Array.isArray(arrayData) || arrayData.length === 0) {
      throw new Error('无可视化数组数据')
    }

    const arr = av.ds.array(arrayData, { indexed: true, center: false })
    jsavArray = arr

    av.displayInit()

    const highlightsMap = buildHighlightsMap()

    for (let i = 0; i < steps.value.length; i++) {
      const step = steps.value[i]

      // 清除上一轮高亮
      for (let j = 0; j < arrayData.length; j++) {
        arr.unhighlight(j)
      }

      // 应用 highlights 中定义的高亮
      const stepHighlights = highlightsMap.get(i) || []
      for (const h of stepHighlights) {
        if (Array.isArray(h.elements)) {
          for (const el of h.elements) {
            if (typeof el === 'number' && el >= 0 && el < arrayData.length) {
              arr.highlight(el)
            }
          }
        }
      }

      // 高亮 step.index
      if (typeof step.index === 'number' && step.index >= 0 && step.index < arrayData.length) {
        arr.highlight(step.index)
      }

      // 处理交换（排序算法）
      if (
        step.type === 'swap' &&
        typeof step.i === 'number' && typeof step.j === 'number' &&
        step.i >= 0 && step.i < arrayData.length &&
        step.j >= 0 && step.j < arrayData.length
      ) {
        const temp = arr.value(step.i)
        arr.value(step.i, arr.value(step.j))
        arr.value(step.j, temp)
        arr.highlight(step.i)
        arr.highlight(step.j)
      }

      // 标记已排序元素
      if (
        step.type === 'mark_sorted' &&
        typeof step.index === 'number' &&
        step.index >= 0 && step.index < arrayData.length
      ) {
        arr.css(step.index, { 'background-color': 'var(--color-success-light)' })
      }

      av.umsg(step.description || `步骤 ${i + 1}`)
      av.step()
    }

    av.recorded()
    av.begin()

    currentStep.value = 0
    jsavActive.value = true
  } catch (err) {
    jsavActive.value = false
    loadState.value = 'failed'
    loadError.value = err?.message || 'JSAV 渲染失败'
    emit('error', loadError.value)
  }
}

function clearJSAV() {
  if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
  if (jsavContainerRef.value) {
    jsavContainerRef.value.innerHTML = ''
  }
  jsavInstance = null
  jsavArray = null
}

/* ════════════════════════════════════════════
   播放控制
   ════════════════════════════════════════════ */

function nextStep() {
  if (!canNext.value) {
    pause()
    return
  }
  currentStep.value++
  if (jsavActive.value && jsavInstance) {
    try { jsavInstance.forward() } catch { /* 忽略导航错误 */ }
  }
  if (!canNext.value) {
    pause()
  }
}

function prevStep() {
  if (!canPrev.value) return
  currentStep.value--
  if (jsavActive.value && jsavInstance) {
    try { jsavInstance.backward() } catch { /* 忽略导航错误 */ }
  }
}

function replay() {
  pause()
  currentStep.value = 0
  if (jsavActive.value && jsavInstance) {
    try { jsavInstance.begin() } catch { /* 忽略导航错误 */ }
  }
}

function jumpToStep(stepIndex) {
  const clamped = Math.max(0, Math.min(stepIndex, totalSteps.value))
  currentStep.value = clamped
  if (jsavActive.value && jsavInstance) {
    try {
      jsavInstance.begin()
      for (let i = 0; i < clamped; i++) {
        jsavInstance.forward()
      }
    } catch { /* 忽略导航错误 */ }
  }
}

function play() {
  if (totalSteps.value === 0) return
  if (!canNext.value) {
    replay()
  }
  isPlaying.value = true
  const interval = Math.max(400, 2000 / playbackSpeed.value)
  playTimer = setInterval(() => {
    if (!canNext.value) {
      pause()
      return
    }
    nextStep()
  }, interval)
}

function pause() {
  isPlaying.value = false
  if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
}

function togglePlay() {
  if (isPlaying.value) {
    pause()
  } else {
    play()
  }
}

function handleReturnAnchor() {
  emit('return-anchor', returnAnchor.value)
}

/* ════════════════════════════════════════════
   生命周期
   ════════════════════════════════════════════ */

onMounted(async () => {
  if (!canUseJSAV.value) {
    loadState.value = 'failed'
    loadError.value = isWhitelisted.value
      ? '该算法类别使用文字步骤模式'
      : '算法不在可视化白名单中'
    return
  }

  await loadJSAV()
  if (loadState.value === 'loaded') {
    await nextTick()
    buildVisualization()
    if (props.autoplay && totalSteps.value > 0) {
      play()
    }
  }
})

watch(
  () => props.planData,
  () => {
    pause()
    currentStep.value = 0
    if (loadState.value === 'loaded' && canUseJSAV.value) {
      nextTick(() => buildVisualization())
    }
  },
  { deep: true },
)

onBeforeUnmount(() => {
  pause()
  clearJSAV()
})
</script>

<template>
  <div class="jsav-player">
    <!-- 头部：算法名称 + 参数 -->
    <header class="jsav-player__header">
      <div class="jsav-player__title-row">
        <Code :size="20" class="jsav-player__algo-icon" />
        <h3 class="jsav-player__name">{{ algorithmName }}</h3>
        <span v-if="algorithmCategory" class="jsav-player__category">{{ algorithmCategory }}</span>
      </div>
      <div v-if="hasParams" class="jsav-player__params">
        <span
          v-for="(value, key) in displayParams"
          :key="key"
          class="jsav-player__param"
        >
          <span class="jsav-player__param-key">{{ key }}</span>
          <span class="jsav-player__param-value">{{ value }}</span>
        </span>
      </div>
    </header>

    <!-- 可视化画布 -->
    <div class="jsav-player__canvas">
      <!-- 加载中 -->
      <div v-if="loadState === 'loading'" class="jsav-player__state jsav-player__state--loading">
        <span class="jsav-player__spinner" role="status" aria-label="加载中" />
        <p class="jsav-player__state-text">正在加载可视化引擎...</p>
      </div>

      <!-- JSAV 渲染容器 -->
      <div v-show="jsavActive" ref="jsavContainerRef" class="jsav-player__jsav-container" />

      <!-- 降级：纯文字步骤列表 -->
      <div v-if="showFallback" class="jsav-player__fallback">
        <div v-if="showWhitelistWarning" class="jsav-player__warning">
          <AlertCircle :size="18" />
          <span>该算法不在可视化白名单中，仅显示步骤说明</span>
        </div>
        <ol class="jsav-player__step-list">
          <li
            class="jsav-player__step-item"
            :class="{ 'is-active': currentStep === 0 }"
            role="button"
            tabindex="0"
            @click="jumpToStep(0)"
            @keydown.enter="jumpToStep(0)"
          >
            <span class="jsav-player__step-index">0</span>
            <span class="jsav-player__step-badge jsav-player__step-badge--initial">initial</span>
            <span class="jsav-player__step-text">初始状态</span>
          </li>
          <li
            v-for="(step, i) in steps"
            :key="i"
            class="jsav-player__step-item"
            :class="{ 'is-active': currentStep === i + 1 }"
            role="button"
            tabindex="0"
            @click="jumpToStep(i + 1)"
            @keydown.enter="jumpToStep(i + 1)"
          >
            <span class="jsav-player__step-index">{{ i + 1 }}</span>
            <span class="jsav-player__step-badge">{{ step.type }}</span>
            <span class="jsav-player__step-text">{{ step.description }}</span>
          </li>
        </ol>
      </div>
    </div>

    <!-- 步骤说明 -->
    <div v-if="totalSteps > 0" class="jsav-player__description">
      <Info :size="16" />
      <span>{{ stepDescription }}</span>
    </div>

    <!-- 进度条 -->
    <div v-if="totalSteps > 0" class="jsav-player__progress">
      <div class="jsav-player__progress-track">
        <div class="jsav-player__progress-fill" :style="{ width: progressPercent + '%' }" />
      </div>
      <span class="jsav-player__progress-text">{{ currentStep }} / {{ totalSteps }}</span>
    </div>

    <!-- 控制栏 -->
    <div class="jsav-player__controls">
      <div class="jsav-player__controls-group">
        <button
          class="jsav-player__btn"
          :disabled="totalSteps === 0"
          aria-label="重放"
          title="重放"
          @click="replay"
        >
          <RotateCcw :size="18" />
        </button>
        <button
          class="jsav-player__btn"
          :disabled="!canPrev"
          aria-label="上一步"
          title="上一步"
          @click="prevStep"
        >
          <SkipBack :size="18" />
        </button>
        <button
          class="jsav-player__btn jsav-player__btn--play"
          :disabled="totalSteps === 0"
          :aria-label="isPlaying ? '暂停' : '播放'"
          :title="isPlaying ? '暂停' : '播放'"
          @click="togglePlay"
        >
          <Pause v-if="isPlaying" :size="20" />
          <Play v-else :size="20" />
        </button>
        <button
          class="jsav-player__btn"
          :disabled="!canNext"
          aria-label="下一步"
          title="下一步"
          @click="nextStep"
        >
          <SkipForward :size="18" />
        </button>
      </div>
      <div class="jsav-player__controls-group">
        <button
          v-if="returnAnchor"
          class="jsav-player__anchor-btn"
          @click="handleReturnAnchor"
        >
          <Link2 :size="16" />
          <span>{{ returnAnchor.label || '返回知识点' }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.jsav-player {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  font-family: var(--font-sans);
}

/* ── 头部 ── */
.jsav-player__header {
  padding: var(--space-4);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-2);
}

.jsav-player__title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.jsav-player__algo-icon {
  color: var(--color-primary);
  flex-shrink: 0;
}

.jsav-player__name {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--color-text);
  line-height: var(--leading-tight);
}

.jsav-player__category {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--color-primary);
  background: var(--color-primary-light);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.jsav-player__params {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.jsav-player__param {
  display: inline-flex;
  align-items: baseline;
  gap: var(--space-1);
  font-size: var(--text-sm);
  font-family: var(--font-mono);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: var(--space-1) var(--space-2);
}

.jsav-player__param-key {
  color: var(--color-text-muted);
}

.jsav-player__param-value {
  color: var(--color-text);
  font-weight: var(--font-medium);
}

/* ── 画布 ── */
.jsav-player__canvas {
  position: relative;
  min-height: 200px;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
}

.jsav-player__jsav-container {
  min-height: 180px;
  overflow-x: auto;
}

/* JSAV 元素基本适配 */
.jsav-player__jsav-container :deep(.jsavcanvas) {
  min-height: 160px;
}

.jsav-player__jsav-container :deep(.jsavnode) {
  font-family: var(--font-mono);
}

.jsav-player__jsav-container :deep(.jsavarray) {
  margin: 0 auto;
}

.jsav-player__jsav-container :deep(.jsavindex) {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}

/* ── 加载状态 ── */
.jsav-player__state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  min-height: 180px;
}

.jsav-player__spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: var(--radius-full);
  animation: jsav-player-spin 0.7s linear infinite;
}

@keyframes jsav-player-spin {
  to {
    transform: rotate(360deg);
  }
}

.jsav-player__state-text {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

/* ── 降级文字步骤列表 ── */
.jsav-player__fallback {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.jsav-player__warning {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--color-warning-light);
  border-radius: var(--radius-md);
  color: var(--color-warning-hover);
  font-size: var(--text-sm);
}

.jsav-player__step-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 360px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.jsav-player__step-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  cursor: pointer;
  transition: var(--transition-color);
}

.jsav-player__step-item:hover {
  background: var(--color-surface-2);
}

.jsav-player__step-item:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.jsav-player__step-item.is-active {
  background: var(--color-primary-light);
  border-color: var(--color-primary);
}

.jsav-player__step-index {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  font-family: var(--font-mono);
  color: var(--color-text-muted);
  background: var(--color-surface-3);
  border-radius: var(--radius-sm);
}

.jsav-player__step-item.is-active .jsav-player__step-index {
  color: var(--color-primary-foreground);
  background: var(--color-primary);
}

.jsav-player__step-badge {
  flex-shrink: 0;
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  color: var(--color-info);
  background: var(--color-info-light);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
}

.jsav-player__step-badge--initial {
  color: var(--color-text-muted);
  background: var(--color-surface-3);
}

.jsav-player__step-text {
  font-size: var(--text-sm);
  color: var(--color-text);
  line-height: var(--leading-normal);
}

/* ── 步骤说明 ── */
.jsav-player__description {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  background: var(--color-surface-2);
  border-top: 1px solid var(--color-border);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
}

.jsav-player__description svg {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--color-primary);
}

/* ── 进度条 ── */
.jsav-player__progress {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-4) var(--space-2);
}

.jsav-player__progress-track {
  flex: 1;
  height: 6px;
  background: var(--color-border);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.jsav-player__progress-fill {
  height: 100%;
  background: var(--gradient-primary);
  border-radius: var(--radius-full);
  transition: width var(--duration-normal) var(--ease);
}

.jsav-player__progress-text {
  flex-shrink: 0;
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  color: var(--color-text-muted);
  min-width: 48px;
  text-align: right;
}

/* ── 控制栏 ── */
.jsav-player__controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-4) var(--space-4);
  gap: var(--space-3);
}

.jsav-player__controls-group {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.jsav-player__btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: var(--transition-color);
}

.jsav-player__btn:hover:not(:disabled) {
  border-color: var(--color-border-hover);
  background: var(--color-surface-2);
  color: var(--color-primary);
}

.jsav-player__btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.jsav-player__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.jsav-player__btn--play {
  width: 48px;
  height: 48px;
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: var(--color-primary-foreground);
  box-shadow: var(--shadow-primary);
}

.jsav-player__btn--play:hover:not(:disabled) {
  background: var(--color-primary-hover);
  border-color: var(--color-primary-hover);
  color: var(--color-primary-foreground);
}

.jsav-player__anchor-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-primary);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: var(--transition-color);
}

.jsav-player__anchor-btn:hover {
  background: var(--color-primary-light);
  border-color: var(--color-primary);
}

.jsav-player__anchor-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .jsav-player__spinner {
    animation-duration: 1.5s;
  }

  .jsav-player__progress-fill {
    transition: none;
  }
}
</style>
