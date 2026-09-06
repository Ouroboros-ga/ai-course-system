<script setup>
/**
 * NX-H1 计划卡：会话当前计划快照（TodoListMiddleware write_todos 投影）。
 * 只读展示：条目 + 原生三态（pending/in_progress/completed）；无百分比、
 * 无定时推进——计划的完成语义以 Runtime 快照为准，取消/中断不改变条目。
 */
import { computed, ref } from 'vue'

const props = defineProps({
  plan: { type: Object, default: null },
})

const expanded = ref(false)

const STATUS_META = {
  pending: { label: '待办', cls: 'pending' },
  in_progress: { label: '进行中', cls: 'active' },
  completed: { label: '已完成', cls: 'done' },
}

const items = computed(() => (Array.isArray(props.plan?.items) ? props.plan.items : []))
const doneCount = computed(() => items.value.filter((i) => i.status === 'completed').length)
const hasActive = computed(() => items.value.some((i) => i.status === 'in_progress'))
const visibleItems = computed(() => (expanded.value ? items.value : items.value.slice(0, 3)))

function statusMeta(status) {
  return STATUS_META[status] || { label: status || '未知', cls: 'pending' }
}
</script>

<template>
  <div v-if="plan && items.length" class="nx-plan-card" role="region" aria-label="当前计划">
    <div class="nx-plan-head">
      <span class="nx-plan-title">计划</span>
      <span class="nx-plan-count">{{ doneCount }}/{{ items.length }}</span>
      <span v-if="hasActive" class="nx-plan-live">执行中</span>
      <span class="nx-plan-rev">rev {{ plan.revision }}</span>
      <button
        v-if="items.length > 3"
        type="button"
        class="nx-plan-toggle"
        @click="expanded = !expanded"
      >
        {{ expanded ? '收起' : `全部 ${items.length} 项` }}
      </button>
    </div>
    <ol class="nx-plan-items">
      <li v-for="item in visibleItems" :key="item.id" class="nx-plan-item">
        <span class="nx-plan-dot" :class="statusMeta(item.status).cls" aria-hidden="true"></span>
        <span class="nx-plan-content" :class="{ done: item.status === 'completed' }">{{ item.content }}</span>
        <span class="nx-plan-status" :class="statusMeta(item.status).cls">{{ statusMeta(item.status).label }}</span>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.nx-plan-card {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-cool);
  padding: 10px 14px;
  margin: 10px 0;
}

.nx-plan-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--caption-size);
  color: var(--text-secondary);
}

.nx-plan-title {
  font-weight: 600;
  color: var(--text-primary);
}

.nx-plan-live {
  color: var(--nexus-accent-strong);
}

.nx-plan-rev {
  color: var(--text-muted);
}

.nx-plan-toggle {
  margin-left: auto;
  border: none;
  background: none;
  color: var(--nexus-accent);
  cursor: pointer;
  font-size: var(--caption-size);
  padding: 0;
}

.nx-plan-items {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nx-plan-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--ui-sm-size);
  color: var(--text-primary);
}

.nx-plan-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.nx-plan-dot.pending {
  background: var(--border-default);
}

.nx-plan-dot.active {
  background: var(--nexus-accent);
}

.nx-plan-dot.done {
  background: var(--nexus-accent-strong);
}

.nx-plan-content.done {
  color: var(--text-muted);
  text-decoration: line-through;
}

.nx-plan-status {
  margin-left: auto;
  font-size: var(--caption-size);
  color: var(--text-muted);
}

.nx-plan-status.active {
  color: var(--nexus-accent-strong);
}
</style>
