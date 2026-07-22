<template>
  <section class="gb-evidence">
    <div class="panel-heading">
      <div>
        <p>证据链</p>
        <small>真实来源：/api/v1/evidence-v2（V2，旗帜管控）</small>
      </div>
      <span class="count" v-if="evidenceNodes.length">{{ evidenceNodes.length }} 条</span>
    </div>

    <div v-if="!documentId" class="ev-empty">
      <FileQuestion :size="18" />
      <p>本课程暂无可用 document_id，无法拉取证据。仅展示映射图谱。</p>
    </div>
    <div v-else-if="error" class="ev-empty warn">
      <AlertTriangle :size="18" />
      <p>{{ error }}</p>
    </div>
    <div v-else-if="!evidenceNodes.length" class="ev-empty">
      <Inbox :size="18" />
      <p>当前文档暂无证据（V2 影子未产生数据，或未放量）。此处不伪造证据。</p>
    </div>

    <ul v-else class="ev-list">
      <li v-for="n in evidenceNodes" :key="n.id" class="ev-item" :class="{ active: selectedId === n.id }" @click="$emit('select', n)">
        <span class="ev-page">P{{ n.pageStart ?? '?' }}</span>
        <span class="ev-body">
          <strong class="ev-doc mono">{{ n.documentId }}</strong>
          <span class="ev-meta">{{ n.citationCount }} 条引用 · 块 {{ n.spanId || '—' }}</span>
        </span>
        <button type="button" class="open" :aria-label="`在证据查看器打开 ${n.documentId}`" @click.stop="openEvidence(n)">
          <ExternalLink :size="14" />
        </button>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { AlertTriangle, ExternalLink, FileQuestion, Inbox } from 'lucide-vue-next'

const props = defineProps({
  evidenceNodes: { type: Array, default: () => [] },
  documentId: { type: String, default: null },
  error: { type: String, default: '' },
  selectedId: { type: String, default: null },
})
defineEmits(['select'])

const router = useRouter()
function openEvidence(n) {
  if (!n.documentId) return
  router.push({ name: 'evidence-viewer', params: { documentId: n.documentId } })
}
</script>

<style scoped>
.gb-evidence { background: var(--color-bg-primary, #fff); border: 1px solid var(--color-border, #d9e1ea); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; min-height: 0; }
.panel-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.panel-heading p { margin: 0; font-size: 14px; font-weight: 700; color: var(--color-text-primary, #1e293b); }
.panel-heading small { display: block; color: var(--color-text-tertiary, #94a3b8); font-size: 11px; margin-top: 2px; }
.count { font-size: 11px; background: var(--color-bg-secondary, #f1f5f9); color: var(--color-text-secondary, #475569); padding: 3px 8px; border-radius: 999px; }
.ev-empty { margin-top: 12px; display: flex; gap: 10px; align-items: center; padding: 12px; background: var(--color-bg-secondary, #f8fafc); border: 1px dashed var(--color-border, #cbd5e1); border-radius: 8px; color: var(--color-text-secondary, #475569); font-size: 12px; }
.ev-empty.warn { background: #fef2f2; border-color: #fecaca; color: #991b1b; }
.ev-empty p { margin: 0; }
.ev-list { margin: 12px 0 0; padding: 0; list-style: none; overflow: auto; }
.ev-item { display: flex; align-items: center; gap: 10px; padding: 8px; border-radius: 8px; cursor: pointer; border: 1px solid transparent; }
.ev-item:hover { background: var(--color-bg-secondary, #f8fafc); }
.ev-item.active { border-color: var(--color-primary, #1769aa); background: #eff6ff; }
.ev-page { flex: none; font-size: 11px; font-weight: 700; color: #a16207; background: #fffbeb; border: 1px solid #fde68a; padding: 2px 6px; border-radius: 6px; }
.ev-body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.ev-doc { font-size: 12px; color: var(--color-text-primary, #1e293b); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mono { font-family: ui-monospace, monospace; }
.ev-meta { font-size: 11px; color: var(--color-text-tertiary, #94a3b8); }
.open { flex: none; width: 28px; height: 28px; border: 1px solid var(--color-border, #cbd5e1); border-radius: 6px; background: var(--color-bg-primary, #fff); color: var(--color-text-secondary, #475569); display: grid; place-items: center; cursor: pointer; }
.open:hover { color: var(--color-primary, #1769aa); border-color: var(--color-primary, #1769aa); }
</style>
