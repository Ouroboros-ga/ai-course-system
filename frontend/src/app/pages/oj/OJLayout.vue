<script setup>
import { onMounted, ref } from 'vue'
import L2TabsLayout from '@/app/shell/L2TabsLayout.vue'
import { listFacadeCourses } from '@/api/facade.js'

/**
 * OJ 题库空间布局（PR-10/08/11/12 前端接入）。
 * 学生 tabs：活动作业｜题库列表｜我的提交｜学情分析。
 * 教师 tabs（有在教课程时追加）：题目管理｜活动管理｜评测记录 ——
 * 纯前端入口显隐，服务端仍按 experiment.configure 强制。
 */
const isTeacher = ref(false)

const studentTabs = [
  { key: 'assignments', label: '活动作业', to: '/app/oj/assignments' },
  { key: 'bank', label: '题库列表', to: '/app/oj/bank' },
  { key: 'submissions', label: '我的提交', to: '/app/oj/submissions' },
  { key: 'analytics', label: '学情分析', to: '/app/oj/analytics' },
]
const teacherTabs = [
  { key: 'teacher-problems', label: '题目管理', to: '/app/oj/teacher/problems' },
  { key: 'teacher-activities', label: '活动管理', to: '/app/oj/teacher/activities' },
  { key: 'teacher-submissions', label: '评测记录', to: '/app/oj/teacher/submissions' },
]

function tabs() {
  return isTeacher.value ? [...studentTabs, ...teacherTabs] : studentTabs
}

onMounted(async () => {
  try {
    const building = await listFacadeCourses('building')
    isTeacher.value = Array.isArray(building) && building.length > 0
  } catch {
    isTeacher.value = false
  }
})
</script>

<template>
  <L2TabsLayout :tabs="tabs()" aria-label="OJ 题库导航" />
</template>
