<script setup>
import L2TabsLayout from '@/app/shell/L2TabsLayout.vue'

/**
 * 平台实验室布局（page-design §2.4）。
 * L2：实验大厅｜课程任务｜我的实验｜学习记录。
 */
const tabs = [
  { key: 'hall', label: '实验大厅', to: '/app/lab/hall' },
  { key: 'course-tasks', label: '课程任务', to: '/app/lab/course-tasks' },
  { key: 'my-experiments', label: '我的实验', to: '/app/lab/my-experiments' },
  { key: 'records', label: '学习记录', to: '/app/lab/records' },
]
</script>

<template>
  <L2TabsLayout :tabs="tabs" aria-label="实验室导航" />
</template>
