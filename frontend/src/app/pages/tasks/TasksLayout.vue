<script setup>
import L2TabsLayout from '@/app/shell/L2TabsLayout.vue'

/**
 * 任务中心布局（page-design §2.6）。
 * L2：我的待办｜我发起的｜系统任务｜已完成。
 */
const tabs = [
  { key: 'todo', label: '我的待办', to: '/app/tasks/todo' },
  { key: 'created', label: '我发起的', to: '/app/tasks/created' },
  { key: 'system', label: '系统任务', to: '/app/tasks/system' },
  { key: 'completed', label: '已完成', to: '/app/tasks/completed' },
]
</script>

<template>
  <L2TabsLayout :tabs="tabs" aria-label="任务中心导航" />
</template>
