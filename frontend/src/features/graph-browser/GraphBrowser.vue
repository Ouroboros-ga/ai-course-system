<template>
  <main class="gb-root">
    <header class="gb-header">
      <div class="identity">
        <button type="button" class="back" aria-label="返回课程生产" @click="goProduction">
          <ArrowLeft :size="18" />
        </button>
        <div>
          <p>教师空间 / 知识图谱浏览器</p>
          <h1>图谱浏览 <span>{{ courseTitle }}</span></h1>
        </div>
      </div>
      <div class="header-actions">
        <span class="flag-note"><ShieldCheck :size="14" /> 仅展示真实接口可证的数据</span>
        <button type="button" class="secondary" :disabled="loading" @click="reload">
          <RefreshCw :size="16" /> 刷新
        </button>
      </div>
    </header>

    <div v-if="error" class="page-error">
      <AlertTriangle :size="18" /><span>{{ error }}</span>
      <button type="button" @click="reload">重试</button>
    </div>

    <div v-else class="gb-grid" :class="{ loading }">
      <section class="canvas-panel">
        <div class="panel-heading">
          <div>
            <p>课程知识图谱</p>
            <small>{{ nodes.length }} 节点 · {{ edges.length }} 边 · 折叠结构（课程→知识点→证据）</small>
          </div>
        </div>
        <div v-if="loading" class="state"><LoaderCircle class="spin" :size="20" />正在装配图谱…</div>
        <div v-else-if="!nodes.length" class="state">暂无可视化数据。请先完成课程解析与映射。</div>
        <GraphCanvas
          v-else
          :nodes="nodes"
          :edges="edges"
          :selected-id="selectedId"
          @select="onSelect"
        />
      </section>

      <div class="side">
        <NodeInspector :node="selected" :course-id="courseId" />
        <RetrievalTracePanel :trace="trace" />
        <EvidenceListPanel
          :evidence-nodes="evidenceNodes"
          :document-id="documentId"
          :error="evidenceError"
          :selected-id="selectedId"
          @select="onSelect"
        />
      </div>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AlertTriangle, ArrowLeft, LoaderCircle, RefreshCw, ShieldCheck } from 'lucide-vue-next'
import GraphCanvas from './components/GraphCanvas.vue'
import NodeInspector from './components/NodeInspector.vue'
import RetrievalTracePanel from './components/RetrievalTracePanel.vue'
import EvidenceListPanel from './components/EvidenceListPanel.vue'
import { useGraphBrowser } from './composables/useGraphBrowser.js'

const route = useRoute()
const router = useRouter()
const courseId = computed(() => route.params.courseId)

const {
  loading, error, evidenceError, courseTitle, documentId,
  nodes, edges, evidenceNodes, trace, load,
} = useGraphBrowser()

const selected = ref(null)
const selectedId = computed(() => selected.value?.id || null)

function onSelect(node) { selected.value = node }
function reload() { load(courseId.value) }
function goProduction() { router.push(`/app/course/${courseId.value}/build`) }

onMounted(() => load(courseId.value))
</script>

<style scoped>
.gb-root { min-height: 100dvh; background: var(--color-bg-secondary, #f5f7fa); color: var(--color-text-primary, #1e293b); }
.gb-header { min-height: 64px; padding: 0 24px; background: var(--color-bg-primary, #fff); border-bottom: 1px solid var(--color-border, #d9e1ea); display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.identity { display: flex; align-items: center; gap: 12px; }
.identity p { margin: 0; color: var(--color-text-secondary, #64748b); font-size: 12px; }
.identity h1 { font-size: 18px; margin: 3px 0 0; }
.identity h1 span { font-weight: 400; color: var(--color-text-secondary, #64748b); font-size: 13px; }
.back { width: 40px; height: 40px; border: 1px solid var(--color-border, #d9e1ea); border-radius: 9px; background: var(--color-bg-primary, #fff); color: var(--color-text-primary, #334155); display: grid; place-items: center; cursor: pointer; }
.header-actions { display: flex; align-items: center; gap: 12px; }
.flag-note { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--color-text-secondary, #475569); background: var(--color-bg-secondary, #f1f5f9); padding: 6px 10px; border-radius: 999px; }
.secondary { min-height: 38px; border-radius: 8px; padding: 0 12px; display: inline-flex; align-items: center; gap: 6px; cursor: pointer; font-size: 13px; font-weight: 600; background: var(--color-bg-primary, #fff); border: 1px solid var(--color-border, #cbd5e1); color: var(--color-text-primary, #334155); }
.page-error { max-width: 800px; margin: 28px auto; padding: 14px; background: #fef2f2; border: 1px solid #fecaca; border-radius: 9px; color: #991b1b; display: flex; gap: 10px; align-items: center; }
.page-error button { margin-left: auto; border: 0; background: transparent; color: var(--color-primary, #1769aa); cursor: pointer; text-decoration: underline; }
.gb-grid { display: grid; grid-template-columns: minmax(420px, 1fr) 340px; gap: 14px; padding: 14px; max-width: 1740px; margin: 0 auto; min-height: calc(100dvh - 64px); box-sizing: border-box; }
.canvas-panel { background: var(--color-bg-primary, #fff); border: 1px solid var(--color-border, #d9e1ea); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; min-height: 0; }
.canvas-panel .panel-heading { margin-bottom: 10px; }
.canvas-panel .panel-heading p { margin: 0; font-size: 14px; font-weight: 700; }
.canvas-panel .panel-heading small { display: block; color: var(--color-text-tertiary, #94a3b8); font-size: 12px; margin-top: 2px; }
.state { flex: 1; display: flex; align-items: center; justify-content: center; gap: 8px; color: var(--color-text-tertiary, #94a3b8); font-size: 13px; min-height: 300px; }
.canvas-panel :deep(.gb-canvas-wrap) { flex: 1; }
.side { display: flex; flex-direction: column; gap: 14px; min-height: 0; overflow: auto; }
.spin { animation: gb-spin 1s linear infinite; }
@keyframes gb-spin { to { transform: rotate(360deg); } }
@media (max-width: 1100px) { .gb-grid { grid-template-columns: 1fr; } }
</style>
