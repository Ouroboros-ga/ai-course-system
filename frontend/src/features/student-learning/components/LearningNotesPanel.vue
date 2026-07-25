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

    <!-- P2 §三.2：保存失败必须提示（page-design §12.8） -->
    <p v-if="syncError" class="sl-note-error" role="alert">
      <span>{{ syncError }}</span>
      <button class="sl-note-error-dismiss" @click="$emit('dismiss-error')">知道了</button>
    </p>

    <!-- P2 §三.2：保存成功后显示笔记入口，但不弹出庆祝页面（page-design §12.8） -->
    <p v-else-if="justFinished" class="sl-note-saved-hint">
      笔记已保存。可在笔记入口查看本次记录。
    </p>

    <p class="sl-note-help">笔记已保存到课程后台，关联当前知识点、页码与播放时间。离线时自动暂存本地，联网后同步。</p>

    <!-- P2 §三.2：手动「完成笔记」后返回课程（page-design §12.8） -->
    <div class="sl-note-actions">
      <button
        class="sl-note-finish"
        :disabled="finishing"
        @click="$emit('finish')"
      >
        {{ finishing ? '保存中…' : '完成笔记' }}
      </button>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { MapPin, NotebookPen } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: String, default: '' },
  nodeTitle: { type: String, default: '' },
  page: { type: Number, default: 1 },
  time: { type: Number, default: 0 },
  // P2 §三.2：保存失败错误消息（空字符串表示无错误）
  syncError: { type: String, default: '' },
  // P2 §三.2：「完成笔记」进行中状态
  finishing: { type: Boolean, default: false },
  // P2 §三.2：最近成功完成的笔记 anchorKey（用于显示入口提示）
  finishedAnchor: { type: String, default: '' },
  // P2 §三.2：当前笔记 anchorKey，用于判断是否刚完成
  currentAnchor: { type: String, default: '' },
})

defineEmits(['update:modelValue', 'finish', 'dismiss-error'])

// 仅当 finishedAnchor 等于 currentAnchor 时显示「已保存」提示（避免跨 anchor 误显示）
const justFinished = computed(() =>
  props.finishedAnchor && props.finishedAnchor === props.currentAnchor
)

function formatTime(seconds) {
  const value = Math.max(0, Number(seconds) || 0)
  const minutes = Math.floor(value / 60)
  const remain = Math.floor(value % 60)
  return minutes + ':' + String(remain).padStart(2, '0')
}
</script>

<style scoped>
.sl-notes {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.sl-panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}
.sl-panel-heading small {
  display: block;
  font-weight: normal;
  font-size: 0.75rem;
  color: var(--text-muted, #888);
}
.sl-note-anchor {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  color: var(--text-secondary, #666);
}
.sl-note-editor textarea {
  width: 100%;
  min-height: 120px;
  padding: 8px;
  border: 1px solid var(--border-default, #ddd);
  border-radius: 6px;
  font-size: 0.9rem;
  resize: vertical;
}
.sl-note-help {
  font-size: 0.75rem;
  color: var(--text-muted, #999);
  margin: 0;
}
.sl-note-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  background: #ffebee;
  border: 1px solid #ef9a9a;
  border-radius: 6px;
  color: #c62828;
  font-size: 0.8rem;
  margin: 0;
}
.sl-note-error-dismiss {
  background: none;
  border: 1px solid #c62828;
  color: #c62828;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 0.75rem;
  cursor: pointer;
}
.sl-note-saved-hint {
  padding: 6px 10px;
  background: #e8f5e9;
  border: 1px solid #a5d6a7;
  border-radius: 6px;
  color: #2e7d32;
  font-size: 0.8rem;
  margin: 0;
}
.sl-note-actions {
  display: flex;
  justify-content: flex-end;
}
.sl-note-finish {
  padding: 6px 18px;
  border: none;
  border-radius: 6px;
  background: var(--accent-primary, #4f8cf7);
  color: #fff;
  font-size: 0.85rem;
  cursor: pointer;
}
.sl-note-finish:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>
