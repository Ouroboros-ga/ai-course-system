<script setup>
/**
 * NX-R1a 证据卡：collect_paper_evidence 返回的证据条目只读展示。
 * 每条证据：来源（用户上传文件标签）、locator（原文定位，缺失如实标注）、
 * 摘录（卡片内截断，完整摘录在报告引用里）、覆盖范围（fulltext_excerpt /
 * abstract_only）。abstract_only 明确提示"仅摘要级内容"，不冒充读过全文。
 */
import { computed } from 'vue'

const props = defineProps({
  evidences: { type: Array, default: () => [] },
  attachmentIds: { type: Array, default: () => [] },
})

const items = computed(() =>
  (Array.isArray(props.evidences) ? props.evidences : []).slice(0, 12)
)

function excerptOf(evidence) {
  const text = String(evidence?.excerpt || '')
  return text.length > 160 ? `${text.slice(0, 160)}…` : text
}

function locatorOf(evidence) {
  return evidence?.locator ? `定位 ${evidence.locator}` : '定位缺失（未提供页码映射）'
}
</script>

<template>
  <div v-if="items.length" class="nx-ev-card" role="region" aria-label="论文证据">
    <div class="nx-ev-head">
      <span class="nx-ev-title">论文证据</span>
      <span class="nx-ev-count">{{ items.length }} 条 · 来自上传 PDF（补充参考）</span>
    </div>
    <ul class="nx-ev-list">
      <li v-for="evidence in items" :key="evidence.evidence_id" class="nx-ev-item">
        <div class="nx-ev-meta">
          <span class="nx-ev-source">{{ evidence.source_title }}</span>
          <span class="nx-ev-locator">{{ locatorOf(evidence) }}</span>
          <span
            class="nx-ev-coverage"
            :class="{ abstract: evidence.coverage === 'abstract_only' }"
          >
            {{ evidence.coverage === 'abstract_only' ? '仅摘要级' : '全文摘录' }}
          </span>
        </div>
        <p class="nx-ev-excerpt">{{ excerptOf(evidence) }}</p>
      </li>
    </ul>
    <p v-if="items.some((e) => e.coverage === 'abstract_only')" class="nx-ev-note">
      标记"仅摘要级"的证据来自解析不完整的上传文件，相关结论建议补传完整全文后复核。
    </p>
  </div>
</template>

<style scoped>
.nx-ev-card {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-panel);
  padding: 10px 14px;
  margin: 10px 0;
}

.nx-ev-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.nx-ev-title {
  font-weight: 600;
  font-size: var(--ui-sm-size);
  color: var(--text-primary);
}

.nx-ev-count {
  font-size: var(--caption-size);
  color: var(--text-muted);
}

.nx-ev-list {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.nx-ev-item {
  border-top: 1px solid var(--border-subtle);
  padding-top: 8px;
}

.nx-ev-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: var(--caption-size);
}

.nx-ev-source {
  font-weight: 600;
  color: var(--text-primary);
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nx-ev-locator {
  color: var(--text-secondary);
}

.nx-ev-coverage {
  color: var(--nexus-accent-strong);
}

.nx-ev-coverage.abstract {
  color: var(--text-muted);
}

.nx-ev-excerpt {
  margin: 4px 0 0;
  font-size: var(--caption-size);
  line-height: var(--caption-line);
  color: var(--text-secondary);
}

.nx-ev-note {
  margin: 8px 0 0;
  font-size: var(--caption-size);
  color: var(--text-muted);
}
</style>
