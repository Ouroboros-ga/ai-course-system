<script setup>
import { onMounted, ref } from 'vue'
import L2TabsLayout from '@/app/shell/L2TabsLayout.vue'
import NexusCodeTutorFloat from '@/app/components/nexus/NexusCodeTutorFloat.vue'
import { listFacadeCourseItems } from '@/api/facade.js'
import { useCounterStore } from '@/stores/counter.js'

/**
 * OJ 题库空间布局（PR-10/08/11/12 前端接入）。
 * 学生 tabs：活动作业｜题库列表｜我的提交｜学情分析。
 * 教师 tabs（有在教课程时追加）：题目管理｜活动管理｜评测记录 ——
 * 纯前端入口显隐，服务端仍按 experiment.configure 强制。
 */
const isTeacher = ref(false)
const counter = useCounterStore()

const studentTabs = [
  { key: 'assignments', label: '活动作业', to: '/app/oj/assignments' },
  { key: 'bank', label: '题库列表', to: '/app/oj/bank' },
  { key: 'submissions', label: '我的提交', to: '/app/oj/submissions' },
  // 「学情分析·OJ 数据看板」目前只呈现**教师口径**数据（作业榜/通过率/
  // 关注学生），且后端端点为 experiment.configure —— 学生打开会 403，
  // 前端把它 catch 成空态，等于把"没权限"显示成"没数据"（误导）。
  // 故**只对教师显示**；学生自己的学情属设计稿④「学习总览」，待其落地。
]
const teacherTabs = [
  { key: 'analytics', label: '学情分析', to: '/app/oj/analytics' },
  { key: 'teacher-problems', label: '题目管理', to: '/app/oj/teacher/problems' },
  { key: 'teacher-activities', label: '活动管理', to: '/app/oj/teacher/activities' },
  { key: 'teacher-submissions', label: '评测记录', to: '/app/oj/teacher/submissions' },
]

function tabs() {
  return isTeacher.value ? [...studentTabs, ...teacherTabs] : studentTabs
}

onMounted(async () => {
  // 教师区入口：有在教课程 **或** 平台管理员（超集权限，服务端仍按
  // experiment.configure 强制）。只看 facade('building') 会把管理员挡在门外，
  // 导致「学情分析·OJ 数据看板」在演示账号下根本不可见（2026-09-12 复核发现）。
  let hasBuildingCourse = false
  try {
    const building = await listFacadeCourseItems('building')
    hasBuildingCourse = building.length > 0
  } catch {
    hasBuildingCourse = false
  }
  isTeacher.value = hasBuildingCourse || counter.canManageUsers
})
</script>

<template>
  <L2TabsLayout :tabs="tabs()" aria-label="OJ 题库导航" />
  <!-- NX-CT1 代码伴学浮窗：只在 OJ 题库空间挂载（fixed 层，不进页面滚动容器） -->
  <NexusCodeTutorFloat v-if="counter.canUseNexus" />
</template>
