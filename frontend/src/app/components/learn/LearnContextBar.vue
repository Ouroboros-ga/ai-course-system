<script setup>
import { ArrowLeft, CloudUpload, Maximize2 } from 'lucide-vue-next'
import SfxBadge from '@/app/ui/SfxBadge.vue'

/**
 * 学习页顶部轻量课程上下文（page-design §12.2）：
 * 课程名 / 当前知识点 / 页码 / 保存状态 / 预览标记。
 * 顶部保持轻量，不放复杂统计和多个按钮。
 */
defineProps({
  courseTitle: { type: String, default: '' },
  nodeTitle: { type: String, default: '' },
  currentPage: { type: Number, default: 1 },
  totalPages: { type: Number, default: 1 },
  saveState: { type: String, default: 'saved' }, // saving | saved | error
  preview: { type: Boolean, default: false },
})

const emit = defineEmits(['back', 'fullscreen'])

const saveText = {
  saving: '正在保存进度…',
  saved: '进度已保存',
  error: '进度保存失败（学习记录可能未更新）',
}
</script>

<template>
  <div class="sfx-learn-bar">
    <button type="button" class="sfx-learn-bar-back" @click="emit('back')">
      <ArrowLeft :size="16" />
      <span>概览</span>
    </button>

    <div class="sfx-learn-bar-context">
      <span class="sfx-learn-bar-course sfx-t-ui">{{ courseTitle }}</span>
      <span class="sfx-learn-bar-sep" aria-hidden="true">/</span>
      <span class="sfx-learn-bar-node sfx-t-ui">{{ nodeTitle || '未选择知识点' }}</span>
      <SfxBadge v-if="preview" tone="amber">学生视角预览</SfxBadge>
    </div>

    <div class="sfx-learn-bar-right">
      <span class="sfx-t-caption">第 {{ currentPage }} / {{ totalPages }} 页</span>
      <span class="sfx-learn-bar-save sfx-t-caption" :class="`is-${saveState}`">
        <CloudUpload :size="13" /> {{ saveText[saveState] || saveText.saved }}
      </span>
      <button type="button" class="sfx-learn-bar-icon" aria-label="全屏讲解" @click="emit('fullscreen')">
        <Maximize2 :size="16" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.sfx-learn-bar {
  height: var(--contextbar-height);
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: 0 var(--space-4);
  background: var(--surface-panel);
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
}

.sfx-learn-bar-back {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 32px;
  padding: 0 var(--space-3);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: var(--ui-sm-size);
  font-weight: 500;
}

.sfx-learn-bar-back:hover {
  background: var(--surface-cool);
  color: var(--ink-700);
}

.sfx-learn-bar-context {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.sfx-learn-bar-course {
  color: var(--text-primary);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sfx-learn-bar-sep { color: var(--text-disabled); }

.sfx-learn-bar-node {
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sfx-learn-bar-right {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.sfx-learn-bar-save { display: inline-flex; align-items: center; gap: var(--space-1); }
.sfx-learn-bar-save.is-saving { color: var(--amber-700); }
.sfx-learn-bar-save.is-error { color: var(--red-700); }

.sfx-learn-bar-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
}

.sfx-learn-bar-icon:hover {
  background: var(--surface-cool);
  color: var(--ink-700);
}
</style>
