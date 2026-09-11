<script setup>
import L2TabsLayout from '@/app/shell/L2TabsLayout.vue'

/**
 * OJ 题库空间布局（PR-10/08/11 前端接入）。
 * L2：题库列表｜我的提交｜学情分析。
 * 学情分析下的「OJ 数据看板」按家良拍板并入既有学情二级菜单（不另立一级）。
 */
const tabs = [
  { key: 'assignments', label: '活动作业', to: '/app/oj/assignments' },
  { key: 'bank', label: '题库列表', to: '/app/oj/bank' },
  { key: 'submissions', label: '我的提交', to: '/app/oj/submissions' },
  { key: 'analytics', label: '学情分析', to: '/app/oj/analytics' },
]
</script>

<template>
  <L2TabsLayout :tabs="tabs" aria-label="OJ 题库导航" />
</template>
