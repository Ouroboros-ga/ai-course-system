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
  z-index: 1;
  width: var(--rail-width);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface-soft);
  border-right: 1px solid var(--border-default);
  transition: width var(--duration-normal) var(--ease-out);
}

.sfx-track.is-collapsed {
  width: var(--rail-width-collapsed);
}

/* 收起按钮：与 BuildLayout .rail-toggle 一致的圆形浮按钮（浮在 rail 与 stage 边界上） */
.sfx-track-toggle {
  position: absolute;
  top: var(--space-3);
  right: -13px;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-full);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 30;
}

.sfx-track-toggle:hover { color: var(--ink-700); border-color: var(--border-strong); }

.sfx-track-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding: var(--space-2);
  gap: 2px;
}

.sfx-track-item {
  position: relative;
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

/* 当前项：浅墨蓝背景 + 左侧 3px 状态线（与 BuildLayout .build-link.active 一致，不再用阴影模拟） */
.sfx-track-item.is-current {
  background: var(--ink-100);
  color: var(--ink-900);
}

.sfx-track-item.is-current::before {
  position: absolute;
  left: 0;
  top: var(--space-2);
  bottom: var(--space-2);
  width: 3px;
  background: var(--ink-900);
  content: "";
  border-radius: var(--radius-full);
}

/* 左侧徽章：current 态 status 圆圈变实色反白徽章 */
.sfx-track-item.is-current .sfx-track-item-status {
  background: var(--ink-900);
  color: var(--surface-panel);
  border-radius: var(--radius-full);
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
