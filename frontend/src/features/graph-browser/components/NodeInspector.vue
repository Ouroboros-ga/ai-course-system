<template>
  <aside class="gb-inspector">
    <div class="panel-heading">
      <div>
        <p>节点详情</p>
        <small>点击画布中的节点查看</small>
      </div>
    </div>

    <div v-if="!node" class="empty">
      <MousePointer2 :size="22" />
      <p>从左侧画布选择一个节点，查看其真实来源数据与可跳转的证据。</p>
    </div>

    <template v-else>
      <div class="node-card" :class="`k-${node.kind}`">
        <p class="eyebrow">{{ kindLabel }}</p>
        <h2>{{ node.label }}</h2>
        <dl>
          <div v-if="node.kind === 'knowledge_point'">
            <dt>PPT 页码范围</dt>
            <dd>{{ pageRangeText }}</dd>
          </div>
          <div v-if="node.kind === 'knowledge_point'">
            <dt>匹配置信度</dt>
            <dd>{{ confidenceText }}</dd>
          </div>
          <div v-if="node.kind === 'knowledge_point'">
            <dt>映射来源</dt>
            <dd>{{ node.isManual ? '教师手动调整' : '自动 / AI 候选' }}</dd>
          </div>
          <div v-if="node.kind === 'evidence'">
            <dt>文档</dt>
            <dd class="mono">{{ node.documentId || '—' }}</dd>
          </div>
          <div v-if="node.kind === 'evidence'">
            <dt>引用数</dt>
            <dd>{{ node.citationCount }}</dd>
          </div>
          <div v-if="node.kind === 'evidence'">
            <dt>页码</dt>
            <dd>{{ node.pageStart ?? '未提供（置空，不伪造）' }}</dd>
          </div>
        </dl>
      </div>

      <div v-if="node.kind === 'evidence'" class="actions">
        <button type="button" class="primary" :disabled="!node.documentId" @click="openEvidence">
          <ExternalLink :size="15" /> 在证据查看器中打开
        </button>
        <p class="hint">跳转到已有的 Evidence Viewer（admin-only），按文档高亮真实证据原文。</p>
      </div>

      <div v-if="node.kind === 'knowledge_point'" class="actions">
        <button type="button" class="secondary" @click="openMapping">
          <Network :size="15" /> 打开映射治理
        </button>
      </div>

      <div class="boundary">
        <Info :size="15" />
        <p>图谱关系推理与影响分析尚无正式接口，此处仅呈现真实接口可证的数据，不做伪造。</p>
      </div>
    </template>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ExternalLink, Info, MousePointer2, Network } from 'lucide-vue-next'

const props = defineProps({
  node: { type: Object, default: null },
  courseId: { type: [String, Number], default: null },
})

const router = useRouter()

const kindLabel = computed(() => ({
  course: '课程',
  knowledge_point: '知识点',
  evidence: '证据',
}[props.node?.kind] || '节点'))

const pageRangeText = computed(() => {
  const n = props.node
  if (!n) return '—'
  if (n.pageStart == null || n.pageEnd == null) return '未映射'
  return `PPT 第 ${n.pageStart}–${n.pageEnd} 页`
})
const confidenceText = computed(() => {
  const c = props.node?.confidence
  return Number.isFinite(c) ? `${Math.round(c * 100)}%` : '未提供'
})

function openEvidence() {
  if (!props.node?.documentId) return
  router.push({ name: 'evidence-viewer', params: { documentId: props.node.documentId } })
}
function openMapping() {
  if (!props.courseId) return
  router.push(`/teacher/course/${props.courseId}/mapping`)
}
</script>

<style scoped>
.gb-inspector { background: var(--color-bg-primary, #fff); border: 1px solid var(--color-border, #d9e1ea); border-radius: 12px; padding: 14px; min-height: 0; overflow: auto; }
.panel-heading p { margin: 0; font-size: 14px; font-weight: 700; color: var(--color-text-primary, #1e293b); }
.panel-heading small { display: block; color: var(--color-text-tertiary, #94a3b8); font-size: 12px; margin-top: 2px; }
.empty { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 40px 12px; color: var(--color-text-tertiary, #94a3b8); text-align: center; font-size: 13px; }
.node-card { margin-top: 12px; border: 1px solid var(--color-border, #d9e1ea); border-left-width: 4px; border-radius: 10px; padding: 12px; }
.node-card.k-course { border-left-color: #1769aa; }
.node-card.k-knowledge_point { border-left-color: #0d9488; }
.node-card.k-evidence { border-left-color: #a16207; }
.eyebrow { margin: 0; font-size: 11px; color: var(--color-text-tertiary, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; }
.node-card h2 { margin: 4px 0 10px; font-size: 15px; color: var(--color-text-primary, #1e293b); }
dl { margin: 0; display: flex; flex-direction: column; gap: 8px; }
dl > div { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; }
dt { color: var(--color-text-secondary, #475569); }
dd { margin: 0; color: var(--color-text-primary, #1e293b); text-align: right; word-break: break-all; }
.mono { font-family: ui-monospace, monospace; font-size: 11px; }
.actions { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
.primary, .secondary { min-height: 36px; border-radius: 8px; padding: 0 12px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; cursor: pointer; font-size: 13px; font-weight: 600; }
.primary { background: var(--color-primary, #1769aa); border: 1px solid var(--color-primary, #1769aa); color: #fff; }
.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.secondary { background: var(--color-bg-primary, #fff); border: 1px solid var(--color-border, #cbd5e1); color: var(--color-text-primary, #334155); }
.hint { margin: 0; font-size: 11px; color: var(--color-text-tertiary, #94a3b8); }
.boundary { margin-top: 14px; display: flex; gap: 8px; padding: 10px; background: var(--color-bg-secondary, #f8fafc); border: 1px dashed var(--color-border, #cbd5e1); border-radius: 8px; font-size: 11px; color: var(--color-text-secondary, #475569); }
.boundary p { margin: 0; }
</style>
