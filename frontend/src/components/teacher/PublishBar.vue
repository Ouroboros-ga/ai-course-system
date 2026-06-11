<template>
  <div class="publish-bar">
    <div class="publish-actions">
      <button class="action-btn save" @click="$emit('save')" :disabled="isSaving">
        {{ isSaving ? '保存中...' : '💾 保存草稿' }}
      </button>
      <button class="action-btn publish" @click="$emit('publish')" :disabled="isPublishing || !canPublish">
        {{ isPublishing ? '发布中...' : (courseStatus === 'published' ? '✅ 已发布' : '🚀 发布课程') }}
      </button>
      <button v-if="courseStatus === 'published'" class="action-btn unpublish" @click="$emit('unpublish')">
        📥 下架课程
      </button>
    </div>
    <div class="status-info">
      <span v-if="lastSavedAt">上次保存: {{ formatTime(lastSavedAt) }}</span>
      <span class="status-badge" :class="courseStatus">{{ statusText }}</span>
    </div>
  </div>
</template>

<script setup>
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
.publish-bar { position: sticky; bottom: 0; background: white; border-top: 1px solid #e5e7eb; padding: 12px 20px; display: flex; justify-content: space-between; align-items: center; z-index: 10; }
.publish-actions { display: flex; gap: 10px; }
.action-btn { padding: 8px 20px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500; transition: all 0.2s; }
.action-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.action-btn.save { background: #f3f4f6; color: #374151; }
.action-btn.save:hover:not(:disabled) { background: #e5e7eb; }
.action-btn.publish { background: linear-gradient(135deg, #059669, #10b981); color: white; }
.action-btn.publish:hover:not(:disabled) { box-shadow: 0 4px 12px rgba(5,150,105,0.3); }
.action-btn.unpublish { background: #fef3c7; color: #92400e; }
.status-info { display: flex; align-items: center; gap: 12px; font-size: 13px; color: #6b7280; }
.status-badge { padding: 3px 10px; border-radius: 99px; font-size: 12px; font-weight: 500; }
.status-badge.draft { background: #fef3c7; color: #92400e; }
.status-badge.published { background: #d1fae5; color: #065f46; }
</style>
