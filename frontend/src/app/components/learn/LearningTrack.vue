<script setup>
import { Check, ChevronLeft, ChevronRight, KeyRound } from 'lucide-vue-next'

/**
 * 学习轨道（page-design §6.9）：章节内知识点列表、当前节点、完成状态。
 * 分支状态下自动收缩为 56px 图标轨（§12.5）；与建设页 Local Rail 外观
 * 骨架一致但数据语义不同。
 */
defineProps({
  nodes: { type: Array, default: () => [] },
  currentIndex: { type: Number, default: 0 },
  completedIds: { type: Array, default: () => [] },
  collapsed: { type: Boolean, default: false },
})

const emit = defineEmits(['select', 'toggle'])

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0)
  const m = Math.floor(value / 60)
  const s = Math.floor(value % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

function nodeState(node, index, props) {
  if (index === props.currentIndex) return 'current'
  if (props.completedIds.includes(node.id)) return 'done'
  return 'todo'
}
</script>

<template>
  <aside class="sfx-track" :class="{ 'is-collapsed': collapsed }" aria-label="学习轨道">
    <button
      type="button"
      class="sfx-track-toggle"
      :aria-label="collapsed ? '展开学习轨道' : '收起学习轨道'"
      @click="emit('toggle')"
    >
      <ChevronRight v-if="collapsed" :size="16" />
      <ChevronLeft v-else :size="16" />
    </button>

    <ol class="sfx-track-list">
      <li v-for="(node, index) in nodes" :key="node.id">
        <button
          type="button"
          class="sfx-track-item"
          :class="`is-${nodeState(node, index, { currentIndex, completedIds })}`"
          :aria-current="index === currentIndex ? 'true' : undefined"
          :aria-label="`知识点 ${index + 1}：${node.title}${completedIds.includes(node.id) ? '（已完成）' : index === currentIndex ? '（当前）' : ''}`"
          :title="collapsed ? node.title : undefined"
          @click="emit('select', index)"
        >
          <span class="sfx-track-item-status" aria-hidden="true">
            <Check v-if="completedIds.includes(node.id) && index !== currentIndex" :size="14" :stroke-width="2.6" />
            <span v-else class="sfx-track-item-index">{{ index + 1 }}</span>
          </span>
          <template v-if="!collapsed">
            <span class="sfx-track-item-title">
              {{ node.title }}
              <KeyRound v-if="node.isKeyPoint" :size="12" class="sfx-track-key" aria-label="重点" />
            </span>
            <span class="sfx-track-item-time sfx-t-caption">{{ formatDuration(node.duration) }}</span>
          </template>
        </button>
      </li>
    </ol>
  </aside>
</template>

<style scoped>
.sfx-track {
  position: relative;
  width: var(--rail-width);
  flex-shrink: 0;
  background: var(--surface-soft);
  border-right: 1px solid var(--border-default);
  overflow-y: auto;
  transition: width var(--duration-normal) var(--ease-out);
}

.sfx-track.is-collapsed {
  width: var(--rail-width-collapsed);
}

.sfx-track-toggle {
  position: sticky;
  top: 0;
  z-index: 2;
  width: 100%;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-soft);
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}

.sfx-track-toggle:hover { color: var(--ink-700); }

.sfx-track-list {
  display: flex;
  flex-direction: column;
  padding: var(--space-2);
  gap: 2px;
}

.sfx-track-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  text-align: left;
  color: var(--text-secondary);
  transition: background var(--duration-fast) var(--ease-out);
}

.sfx-track-item:hover { background: var(--surface-cool); }

/* 当前项：浅墨蓝背景 + 左侧 3px 状态线（design.md 4.6） */
.sfx-track-item.is-current {
  background: var(--ink-100);
  color: var(--ink-900);
  box-shadow: inset 3px 0 0 var(--ink-900);
}

.sfx-track-item.is-done { color: var(--green-700); }

.sfx-track-item-status {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.sfx-track-item-index {
  font-size: var(--caption-size);
  font-weight: 600;
  color: inherit;
}

.sfx-track-item-title {
  flex: 1;
  min-width: 0;
  font-size: var(--ui-sm-size);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.sfx-track-key { color: var(--amber-500); flex-shrink: 0; }

.sfx-track-item-time { flex-shrink: 0; }
</style>
