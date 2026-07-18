<template>
  <header class="sl-header">
    <div class="sl-header__course">
      <button type="button" class="sl-icon-button" aria-label="返回课程列表" @click="$emit('back')">
        <ArrowLeft :size="20" />
      </button>
      <div class="sl-header__titles">
        <p>{{ courseTitle }}</p>
        <h1>{{ nodeTitle || '课程学习空间' }}</h1>
      </div>
    </div>

    <div class="sl-mode-switch" role="group" aria-label="学习模式">
      <button
        type="button"
        :class="{ active: mode === 'guided' }"
        :aria-pressed="mode === 'guided'"
        @click="$emit('mode-change', 'guided')"
      >
        <PlayCircle :size="17" />
        <span>跟随讲解</span>
      </button>
      <button
        type="button"
        :class="{ active: mode === 'study' }"
        :aria-pressed="mode === 'study'"
        @click="$emit('mode-change', 'study')"
      >
        <PanelsTopLeft :size="17" />
        <span>课件研习</span>
      </button>
    </div>

    <div class="sl-header__status">
      <div class="sl-progress-summary" :aria-label="'课程进度 ' + Math.round(progress) + '%'">
        <span>{{ Math.round(progress) }}%</span>
        <i><b :style="{ width: progress + '%' }"></b></i>
      </div>
      <span class="sl-save-state" :class="'is-' + saveState">
        <Cloud v-if="saveState === 'saved'" :size="15" />
        <LoaderCircle v-else-if="saveState === 'saving'" :size="15" class="sl-spin" />
        <CloudAlert v-else :size="15" />
        {{ saveLabel }}
      </span>
      <div class="sl-header__actions">
        <button
          type="button"
          class="sl-icon-button sl-desktop-toggle"
          :aria-pressed="outlineOpen"
          aria-label="切换课程目录"
          @click="$emit('toggle-panel', 'outline')"
        >
          <ListTree :size="19" />
        </button>
        <button
          type="button"
          class="sl-icon-button"
          :aria-pressed="notesOpen"
          aria-label="打开学习笔记"
          @click="$emit('toggle-panel', 'notes')"
        >
          <NotebookPen :size="19" />
        </button>
        <button
          type="button"
          class="sl-icon-button"
          :aria-pressed="assistantOpen"
          aria-label="切换课程智能体"
          @click="$emit('toggle-panel', 'assistant')"
        >
          <MessageSquareText :size="19" />
        </button>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import {
  ArrowLeft,
  Cloud,
  CloudAlert,
  ListTree,
  LoaderCircle,
  MessageSquareText,
  NotebookPen,
  PanelsTopLeft,
  PlayCircle,
} from 'lucide-vue-next'

const props = defineProps({
  courseTitle: { type: String, default: '' },
  nodeTitle: { type: String, default: '' },
  mode: { type: String, required: true },
  progress: { type: Number, default: 0 },
  saveState: { type: String, default: 'saved' },
  outlineOpen: { type: Boolean, default: true },
  assistantOpen: { type: Boolean, default: true },
  notesOpen: { type: Boolean, default: false },
})

defineEmits(['back', 'mode-change', 'toggle-panel'])

const saveLabel = computed(() => {
  if (props.saveState === 'saving') return '保存中'
  if (props.saveState === 'error') return '保存失败'
  return '已保存'
})
</script>