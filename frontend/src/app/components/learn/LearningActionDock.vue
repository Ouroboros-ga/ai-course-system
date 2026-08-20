<script setup>
import { computed, ref } from 'vue'
import { BookOpenText, Code2, LineChart, MessageCircleQuestion, StickyNote } from 'lucide-vue-next'
import { DOCK_ACTIONS } from '@/app/lib/learnMachine.js'

/**
 * 教学行动工具坞（page-design §6.10）：固定顺序 提问｜试一试｜看可视化｜做笔记｜原文引用。
 * 切片 0.1 只启用 提问 / 原文引用；其余禁用并说明条件（§1.5），
 * 不放无功能入口，不加入「聊天」「Agent」等模糊入口。
 */
const props = defineProps({
  currentState: { type: String, required: true },
  enabledStates: { type: Function, required: true }, // (state) => boolean
})

const emit = defineEmits(['action'])

const rootRef = ref(null)
function focus() {
  rootRef.value?.focus()
}
defineExpose({ focus })

const iconMap = {
  ask: MessageCircleQuestion,
  practice: Code2,
  visualize: LineChart,
  note: StickyNote,
  citation: BookOpenText,
}

const items = computed(() =>
  DOCK_ACTIONS.map((action) => ({
    ...action,
    icon: iconMap[action.id],
    enabled: props.enabledStates(action.target),
    active: props.currentState === action.target,
  }))
)
</script>

<template>
  <footer class="sfx-dock" ref="rootRef" tabindex="-1" aria-label="教学行动工具坞">
    <!-- 特殊场景：工具坞动作项，v-for 列表项且包裹 icon+label 富文本，含 aria-pressed 切换态与自定义 is-active/is-disabled 视觉，保留原生 button（design.md §9.1 例外） -->
    <button
      v-for="item in items"
      :key="item.id"
      type="button"
      class="sfx-dock-item"
      :class="{ 'is-active': item.active, 'is-disabled': !item.enabled }"
      :aria-pressed="item.active"
      :aria-disabled="!item.enabled"
      :title="item.enabled ? item.label : `「${item.label}」将在后续切片上线`"
      @click="item.enabled && emit('action', item)"
    >
      <component :is="item.icon" :size="18" />
      <span>{{ item.label }}</span>
    </button>
  </footer>
</template>

<style scoped>
.sfx-dock {
  height: var(--dock-height);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  background: var(--surface-panel);
  border-top: 1px solid var(--border-default);
}

.sfx-dock-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: 40px;
  padding: 0 var(--space-4);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: var(--ui-md-size);
  font-weight: var(--ui-md-weight);
  transition: background var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
}

.sfx-dock-item:hover:not(.is-disabled):not(.is-active) {
  background: var(--surface-cool);
  color: var(--ink-700);
}

.sfx-dock-item.is-active {
  background: var(--ink-100);
  color: var(--ink-900);
}

.sfx-dock-item.is-disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

/* 移动端（design.md §12.5）：5 个动作等宽压缩，去掉多余留白，icon+短标仍可容纳 */
@media (max-width: 760px) {
  .sfx-dock {
    gap: var(--space-1);
    padding-inline: var(--space-2);
    justify-content: stretch;
  }

  .sfx-dock-item {
    flex: 1 1 0;
    min-width: 0;
    justify-content: center;
    gap: var(--space-1);
    height: 36px;
    padding: 0 var(--space-1);
    font-size: var(--ui-sm-size);
    white-space: nowrap;
  }

  .sfx-dock-item span {
    overflow: hidden;
    text-overflow: ellipsis;
  }
}
</style>
