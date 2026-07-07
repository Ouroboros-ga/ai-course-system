<template>
  <div class="publish-bar">
    <div class="publish-actions">
      <button class="action-btn save" @click="$emit('save')" :disabled="isSaving">
        <Save v-if="!isSaving" :size="16" />
        {{ isSaving ? '保存中...' : '保存草稿' }}
      </button>
      <button class="action-btn publish" @click="$emit('publish')" :disabled="isPublishing || !canPublish">
        <CheckCircle v-if="!isPublishing && courseStatus === 'published'" :size="16" />
        <Rocket v-else-if="!isPublishing" :size="16" />
        {{ isPublishing ? '发布中...' : (courseStatus === 'published' ? '已发布' : '发布课程') }}
      </button>
      <button v-if="courseStatus === 'published'" class="action-btn unpublish" @click="$emit('unpublish')">
        <Download :size="16" /> 下架课程
      </button>
    </div>
    <div class="status-info">
      <span v-if="lastSavedAt">上次保存: {{ formatTime(lastSavedAt) }}</span>
      <span class="status-badge" :class="courseStatus">{{ statusText }}</span>
    </div>
  </div>
</template>

<script setup>
import { Save, CheckCircle, Rocket, Download } from 'lucide-vue-next'

defineProps({
  isSaving: Boolean,
  isPublishing: Boolean,
  canPublish: Boolean,
  courseStatus: { type: String, default: 'draft' },
  lastSavedAt: [String, Date],
  statusText: { type: String, default: '' },
})

defineEmits(['save', 'publish', 'unpublish'])

function formatTime(date) {
  if (!date) return ''
  const d = new Date(date)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}
</script>

<style scoped>
.publish-bar { position: sticky; bottom: 0; background: var(--color-surface); border-top: 1px solid var(--color-border); padding: var(--space-3) var(--space-5); display: flex; justify-content: space-between; align-items: center; z-index: var(--z-sticky); }
.publish-actions { display: flex; gap: var(--space-2); }
.action-btn { display: inline-flex; align-items: center; gap: var(--space-1); padding: var(--space-2) var(--space-5); border: none; border-radius: var(--radius-md); cursor: pointer; font-size: var(--text-sm); font-weight: var(--font-medium); transition: var(--transition-all); }
.action-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.action-btn.save { background: var(--color-surface-2); color: var(--color-text-secondary); }
.action-btn.save:hover:not(:disabled) { background: var(--color-surface-3); }
.action-btn.publish { background: var(--gradient-success); color: var(--color-primary-foreground); }
.action-btn.publish:hover:not(:disabled) { transform: translateY(-2px); box-shadow: var(--shadow-success); }
.action-btn.unpublish { background: var(--color-warning-light); color: var(--color-warning-hover); }
.action-btn.unpublish:hover:not(:disabled) { transform: translateY(-2px); }
.status-info { display: flex; align-items: center; gap: var(--space-3); font-size: var(--text-sm); color: var(--color-text-secondary); }
.status-badge { padding: var(--space-1) var(--space-2); border-radius: var(--radius-full); font-size: var(--text-xs); font-weight: var(--font-medium); }
.status-badge.draft { background: var(--color-warning-light); color: var(--color-warning-hover); }
.status-badge.published { background: var(--color-success-light); color: var(--color-success-hover); }
</style>
