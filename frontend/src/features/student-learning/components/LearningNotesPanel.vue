<template>
  <section class="sl-notes" aria-label="学习笔记">
    <header class="sl-panel-heading">
      <div>
        <span>学习笔记</span>
        <small>关联知识点与课件位置</small>
      </div>
      <NotebookPen :size="18" />
    </header>

    <div class="sl-note-anchor">
      <MapPin :size="15" />
      <span>{{ nodeTitle || '课程' }} · 第 {{ page }} 页 · {{ formatTime(time) }}</span>
    </div>

    <label class="sl-note-editor">
      <span class="sl-visually-hidden">当前学习位置笔记</span>
      <textarea
        :value="modelValue"
        placeholder="记录你的理解、疑问或复习提示…"
        @input="$emit('update:modelValue', $event.target.value)"
      ></textarea>
    </label>
    <p class="sl-note-help">笔记仅保存在当前浏览器，不会上传到课程后台。</p>
  </section>
</template>

<script setup>
import { MapPin, NotebookPen } from 'lucide-vue-next'

defineProps({
  modelValue: { type: String, default: '' },
  nodeTitle: { type: String, default: '' },
  page: { type: Number, default: 1 },
  time: { type: Number, default: 0 },
})

defineEmits(['update:modelValue'])

function formatTime(seconds) {
  const value = Math.max(0, Number(seconds) || 0)
  const minutes = Math.floor(value / 60)
  const remain = Math.floor(value % 60)
  return minutes + ':' + String(remain).padStart(2, '0')
}
</script>