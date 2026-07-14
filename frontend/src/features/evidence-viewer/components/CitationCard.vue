<template>
  <div
    class="ev-citation-card"
    :class="{
      'ev-citation--active': isSelected,
      'ev-citation--no-evidence': citation.key == null,
      'ev-citation--stale': isStaleCitation,
    }"
    :data-citation-key="citation.key ?? 'no-evidence'"
    role="button"
    tabindex="0"
    :aria-pressed="isSelected"
    :aria-label="ariaLabel"
    @click="$emit('select', citation.key)"
    @keydown.enter="$emit('select', citation.key)"
    @keydown.space.prevent="$emit('select', citation.key)"
    @mouseenter="$emit('hover', citation.key)"
    @mouseleave="$emit('unhover')"
  >
    <!-- Header row -->
    <div class="ev-citation-header">
      <span class="ev-citation-icon" aria-hidden="true">
        <template v-if="citation.key == null">&#9888;</template>
        <template v-else-if="isStaleCitation">&#9888;</template>
        <template v-else>&#128279;</template>
      </span>
      <span class="ev-citation-confidence" v-if="citation.confidence != null">
        {{ (citation.confidence * 100).toFixed(0) }}%
      </span>
      <StatusIndicator
        v-if="isStaleCitation"
        status="stale"
        size="sm"
      />
      <StatusIndicator
        v-if="citation.key == null"
        status="missing"
        size="sm"
      />
      <span class="ev-citation-page" v-if="citation.pageOrSlide != null">
        p.{{ citation.pageOrSlide }}
      </span>
    </div>

    <!-- Statement text -->
    <p class="ev-citation-statement">{{ citation.statement }}</p>

    <!-- Evidence key -->
    <div class="ev-citation-footer" v-if="citation.key != null">
      <code class="ev-citation-key">{{ citation.key }}</code>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import StatusIndicator from './StatusIndicator.vue'
import { CitationStatus } from '../contracts.js'

const props = defineProps({
  citation: { type: Object, required: true },
  isSelected: { type: Boolean, default: false },
  isStale: { type: Boolean, default: false },
})

defineEmits(['select', 'hover', 'unhover'])

const isStaleCitation = computed(() => {
  return props.isStale || props.citation.key?.startsWith('cit_stale')
})

const ariaLabel = computed(() => {
  const prefix = props.isStaleCitation
    ? 'Stale citation'
    : props.citation.key == null
      ? 'Citation without evidence'
      : 'Citation'
  return `${prefix}: ${props.citation.statement}`
})
</script>

<style scoped>
.ev-citation-card {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.15s ease;
  background: #fff;
  user-select: none;
}

.ev-citation-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.ev-citation--active {
  border-color: #3b82f6;
  background: #eff6ff;
  box-shadow: 0 0 0 1px #3b82f6;
}

.ev-citation--stale {
  border-color: #fde68a;
  background: #fffbeb;
}

.ev-citation--no-evidence {
  border-color: #e5e7eb;
  background: #f9fafb;
  cursor: default;
  opacity: 0.7;
}

.ev-citation-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.ev-citation-icon {
  font-size: 14px;
  line-height: 1;
}

.ev-citation-confidence {
  font-size: 11px;
  color: #6b7280;
  font-weight: 500;
}

.ev-citation-page {
  margin-left: auto;
  font-size: 11px;
  color: #9ca3af;
}

.ev-citation-statement {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: #1f2937;
  overflow-wrap: break-word;
}

.ev-citation-footer {
  margin-top: 6px;
}

.ev-citation-key {
  font-size: 10px;
  color: #9ca3af;
  background: #f3f4f6;
  padding: 1px 4px;
  border-radius: 3px;
}
</style>
