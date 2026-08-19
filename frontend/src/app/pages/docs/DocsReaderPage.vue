<script setup>
/**
 * Docs Reader — 顶层公开 PDF / Word 在线阅读器（不挂 AppShell，无需登录）。
 *
 * - 通过 /docs/view?file=<相对路径>&name=<标题> 打开，file 相对 /docs 静态目录。
 * - PDF：浏览器原生查看器（iframe），零依赖。
 * - DOCX：动态加载 docx-preview（jsdelivr → unpkg 双 CDN 兜底），客户端渲染；
 *   CDN 不可用时降级为下载链接，不伪造渲染结果。
 * - file 参数做了白名单校验（仅允许字母数字、下划线、连字符、斜杠、中文与 pdf/docx/doc 扩展名），
 *   并禁止 .. 与绝对路径，避免目录穿越。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AlertCircle, ArrowLeft, Download, LoaderCircle } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'

const route = useRoute()
const router = useRouter()

const FILE_RE = /^[A-Za-z0-9_\-\/\u4e00-\u9fa5]+\.(pdf|docx|doc)$/

const fileParam = computed(() => (route.query.file || '').toString())
const nameParam = computed(() => (route.query.name || '').toString().trim() || '文档')

const valid = computed(() => {
  const f = fileParam.value
  return !!f && FILE_RE.test(f) && !f.includes('..') && !f.startsWith('/')
})

const isPdf = computed(() => valid.value && /\.pdf$/i.test(fileParam.value))
const isDocx = computed(() => valid.value && /\.docx$/i.test(fileParam.value))
const isLegacyDoc = computed(() => valid.value && /\.doc$/i.test(fileParam.value))

const fileUrl = computed(() => {
  if (!valid.value) return ''
  return `/docs/${fileParam.value.split('/').map(encodeURIComponent).join('/')}`
})

function downloadCurrent() {
  if (!valid.value) return
  const a = document.createElement('a')
  a.href = fileUrl.value
  a.download = ''
  document.body.appendChild(a)
  a.click()
  a.remove()
}

const status = ref('loading') // loading | ready | error
const errorMsg = ref('')
const docxHost = ref(null)
const pdfReady = ref(false)
const pdfKey = ref(0)

let ctrl = null

function retry() {
  status.value = 'loading'
  errorMsg.value = ''
  if (isPdf.value) {
    pdfReady.value = false
    pdfKey.value += 1
    status.value = 'ready'
  } else if (isDocx.value) {
    loadDocx()
  } else if (isLegacyDoc.value) {
    status.value = 'error'
    errorMsg.value = '暂不支持旧版 .doc 在线阅读，请下载后使用 Word 打开。'
  } else {
    status.value = 'error'
    errorMsg.value = '文档地址无效或格式不受支持。'
  }
}

watch(fileParam, () => {
  pdfReady.value = false
  status.value = 'loading'
  ctrl?.abort()
  ctrl = null
  const f = fileParam.value
  if (!valid.value) {
    status.value = 'error'
    errorMsg.value = '文档地址无效或格式不受支持。'
    return
  }
  if (isLegacyDoc.value) {
    status.value = 'error'
    errorMsg.value = '暂不支持旧版 .doc 在线阅读，请下载后使用 Word 打开。'
    return
  }
  if (isPdf.value) {
    status.value = 'ready'
    return
  }
  if (isDocx.value) loadDocx()
})

/* ── docx-preview 动态加载（双 CDN 兜底，不写进 package.json） ── */
let docxLibPromise = null

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = src
    s.onload = () => resolve()
    s.onerror = () => {
      s.remove()
      reject(new Error('script load failed'))
    }
    document.head.appendChild(s)
  })
}

function ensureDocxLib() {
  if (window.docx?.renderAsync) return Promise.resolve()
  if (docxLibPromise) return docxLibPromise
  const urls = [
    'https://cdn.jsdelivr.net/npm/docx-preview@0.3.2/dist/docx-preview.min.js',
    'https://unpkg.com/docx-preview@0.3.2/dist/docx-preview.min.js',
  ]
  docxLibPromise = (async () => {
    for (const url of urls) {
      try {
        await loadScript(url)
        if (window.docx?.renderAsync) return
      } catch {
        /* 尝试下一个 CDN */
      }
    }
    throw new Error('Word 阅读组件加载失败，请检查网络，或直接下载后查看。')
  })()
  return docxLibPromise
}

async function loadDocx() {
  status.value = 'loading'
  errorMsg.value = ''
  ctrl?.abort()
  ctrl = new AbortController()
  try {
    await ensureDocxLib()
    const res = await fetch(fileUrl.value, { signal: ctrl.signal })
    if (!res.ok) throw new Error(`文档加载失败（HTTP ${res.status}）`)
    const blob = await res.blob()
    await nextTick()
    const host = docxHost.value
    if (!host) return
    host.innerHTML = ''
    await window.docx.renderAsync(blob, host)
    status.value = 'ready'
  } catch (err) {
    if (err?.name === 'AbortError') return
    status.value = 'error'
    errorMsg.value = err?.message || '文档渲染失败'
  }
}

onMounted(() => {
  retry()
})

onBeforeUnmount(() => {
  ctrl?.abort()
  ctrl = null
})
</script>

<template>
  <div class="sfx docs-reader">
    <header class="reader-nav">
      <div class="reader-nav__left">
        <SfxButton variant="tertiary" size="sm" @click="router.push('/docs')">
          <template #icon><ArrowLeft :size="16" /></template>
          文档中心
        </SfxButton>
        <span class="reader-nav__divider" aria-hidden="true"></span>
        <h1 class="reader-title">{{ nameParam }}</h1>
        <span v-if="valid" class="reader-badge" :class="isPdf ? 'is-pdf' : 'is-docx'">
          {{ isPdf ? 'PDF' : isLegacyDoc ? 'DOC' : 'DOCX' }}
        </span>
      </div>
      <div class="reader-nav__right">
        <SfxButton v-if="valid" variant="secondary" size="sm" @click="downloadCurrent">
          <template #icon><Download :size="14" /></template>
          下载
        </SfxButton>
      </div>
    </header>

    <div class="reader-body">
      <div v-if="status === 'loading'" class="reader-state" role="status" aria-live="polite">
        <LoaderCircle :size="26" class="reader-spin" aria-hidden="true" />
        <p>正在加载文档…</p>
      </div>

      <div v-else-if="status === 'error'" class="reader-state is-error" role="alert">
        <AlertCircle :size="26" aria-hidden="true" />
        <p>{{ errorMsg }}</p>
        <div class="reader-state__actions">
          <SfxButton v-if="valid" variant="secondary" size="sm" @click="downloadCurrent">下载文档</SfxButton>
          <SfxButton variant="tertiary" size="sm" @click="retry">重试</SfxButton>
        </div>
      </div>

      <template v-else-if="isPdf">
        <iframe
          v-show="pdfReady"
          :key="pdfKey"
          class="pdf-frame"
          :src="fileUrl"
          title="PDF 预览"
          @load="pdfReady = true"
        ></iframe>
        <div v-if="!pdfReady" class="reader-state" role="status" aria-live="polite">
          <LoaderCircle :size="26" class="reader-spin" aria-hidden="true" />
          <p>正在加载 PDF…</p>
        </div>
      </template>

      <div v-else-if="isDocx" ref="docxHost" class="docx-host"></div>
    </div>
  </div>
</template>

<style>
/* 独立公开页：自载 Academic Ink 令牌与基础样式（AppShell 不会为 /docs/view 挂载） */
@import '../../styles/tokens.css';
@import '../../styles/base.css';
</style>

<style scoped>
.docs-reader {
  height: 100dvh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--surface-page);
}

/* ── 顶栏 ── */
.reader-nav {
  flex-shrink: 0;
  height: var(--nav-l1-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: 0 var(--space-4) 0 var(--space-2);
  background: var(--surface-panel);
  border-bottom: 1px solid var(--border-default);
}

.reader-nav__left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.reader-nav__divider {
  width: 1px;
  height: 20px;
  background: var(--border-default);
  flex-shrink: 0;
}

.reader-title {
  font-size: var(--ui-md-size);
  font-weight: var(--ui-md-weight);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.reader-badge {
  flex-shrink: 0;
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--caption-size);
  font-weight: var(--caption-weight);
}

.reader-badge.is-pdf {
  background: var(--red-100);
  color: var(--red-700);
}

.reader-badge.is-docx {
  background: var(--ink-100);
  color: var(--ink-700);
}

/* ── 阅读区 ── */
.reader-body {
  flex: 1;
  min-height: 0;
  position: relative;
  background: var(--surface-cool);
}

.pdf-frame {
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
  background: var(--surface-panel);
}

.docx-host {
  height: 100%;
  overflow-y: auto;
  padding: var(--space-6);
  background: var(--surface-cool);
}

.docx-host :deep(.docx-wrapper) {
  background: transparent;
  padding: 0;
}

.docx-host :deep(.docx-wrapper > section.docx) {
  margin-bottom: var(--space-6);
  box-shadow: var(--shadow-sm);
}

/* ── 加载 / 错误状态 ── */
.reader-state {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  color: var(--text-muted);
  font-size: var(--ui-md-size);
}

.reader-state p {
  margin: 0;
}

.reader-state.is-error {
  color: var(--red-700);
}

.reader-state__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.reader-spin {
  color: var(--ink-500);
  animation: reader-spin 0.9s linear infinite;
}

@keyframes reader-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
