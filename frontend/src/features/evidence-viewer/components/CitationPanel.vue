<template>
  <aside class="ev-citation-panel" role="complementary" aria-label="Citation panel">
    <header class="ev-panel-header">
      <h3 class="ev-panel-title">Citations</h3>
      <span class="ev-panel-count">{{ visibleCitations.length }}</span>
    </header>

    <!-- Stale evidence warning banner -->
    <div v-if="hasStaleEvidence" class="ev-stale-banner" role="alert">
      <span aria-hidden="true">&#9888;</span>
      <span>Some evidence refers to a superseded document version. Verify accuracy before use.</span>
    </div>

    <!-- Citation list -->
    <div class="ev-citation-list" v-if="visibleCitations.length > 0">
      <CitationCard
        v-for="cit in visibleCitations"
        :key="cit.key ?? 'no-evidence-' + cit.statement"
        :citation="cit"
        :isSelected="activeKey === cit.key"
        :isStale="isStale(cit)"
        @select="onSelect"
        @hover="onHover"
        @unhover="onUnhover"
      />
    </div>

    <!-- Empty state -->
    <div v-else class="ev-citation-empty">
      <p>No citations for this page.</p>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="ev-citation-loading">
      <span class="ev-spinner" aria-hidden="true"></span>
      <span>Loading citations...</span>
    </div>

    <!-- Error state -->
    <div v-if="error" class="ev-citation-error" role="alert">
      <p>{{ error }}</p>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import CitationCard from './CitationCard.vue'

const props = defineProps({
  citations: { type: Array, default: () => [] },
  activeCitationKey: { type: String, default: null },
  currentPage: { type: Number, default: 1 },
  hasStaleEvidence: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
})

const emit = defineEmits(['select-citation', 'hover-citation', 'unhover-citation'])

/** Citations visible on the current page */
const visibleCitations = computed(() => {
  return props.citations.filter(cit => {
    // Citations with no page/slide info are shown on all pages
    if (cit.pageOrSlide == null) return true
    return cit.pageOrSlide === props.currentPage
  })
})

function isStale(cit) {
  return cit.key?.startsWith('cit_stale') ?? false
}

function onSelect(key) {
  emit('select-citation', key)
}

function onHover(key) {
  emit('hover-citation', key)
}

function onUnhover() {
  emit('unhover-citation')
}
</script>

<style scoped>
.ev-citation-panel {
  width: 320px;
  min-width: 280px;
  max-width: 400px;
  border-left: 1px solid #e5e7eb;
  background: #fafbfc;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.ev-panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid #e5e7eb;
  background: #fff;
  flex-shrink: 0;
}

.ev-panel-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
}

.ev-panel-count {
  font-size: 11px;
  color: #6b7280;
  background: #f3f4f6;
  padding: 1px 6px;
  border-radius: 8px;
}

.ev-stale-banner {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px 14px;
  background: #fffbeb;
  border-bottom: 1px solid #fde68a;
  font-size: 12px;
  color: #92400e;
  line-height: 1.4;
}

.ev-citation-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 14px;
  flex: 1;
  overflow-y: auto;
}

.ev-citation-empty {
  padding: 32px 14px;
  text-align: center;
  color: #9ca3af;
  font-size: 13px;
}

.ev-citation-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 14px;
  color: #6b7280;
  font-size: 13px;
}

.ev-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid #e5e7eb;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: ev-spin 0.6s linear infinite;
}

@keyframes ev-spin {
  to { transform: rotate(360deg); }
}

.ev-citation-error {
  padding: 12px 14px;
  color: #dc2626;
  font-size: 12px;
  background: #fef2f2;
  border-top: 1px solid #fecaca;
}
</style>
