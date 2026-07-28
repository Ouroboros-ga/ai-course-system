<script setup>
import L2TabsLayout from '@/app/shell/L2TabsLayout.vue'

/**
 * 资源库布局（page-design §2.5）。
 * L2：我的文件｜课程引用｜最近使用｜回收站。
 */
const tabs = [
  { key: 'files', label: '我的文件', to: '/app/resources/files' },
  { key: 'course-materials', label: '课程资料', to: '/app/resources/course-materials' },
  { key: 'course-links', label: '课程引用', to: '/app/resources/course-links' },
  { key: 'recent', label: '最近使用', to: '/app/resources/recent' },
  { key: 'trash', label: '回收站', to: '/app/resources/trash' },
]
</script>

<template>
  <L2TabsLayout :tabs="tabs" aria-label="资源库导航" />
</template>
