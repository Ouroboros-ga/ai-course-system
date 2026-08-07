<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { getLearningAnalytics, getStudentLearningAnalytics } from '@/api/facade.js'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const { courseId } = inject('courseContext')
const state = ref('loading')
const error = ref('')
const analytics = ref(null)
const selectedStudent = ref(null)
const studentDetail = ref(null)
const points = computed(() => analytics.value?.knowledge_points || [])
const students = computed(() => analytics.value?.students || [])

async function load() {
  state.value = 'loading'
  error.value = ''
  try {
    const response = await getLearningAnalytics(courseId.value)
    analytics.value = response?.data ?? response
    state.value = 'ready'
  } catch (e) {
    error.value = e?.message || '学习统计加载失败'
    state.value = 'error'
  }
}

async function inspectStudent(studentId) {
  selectedStudent.value = studentId
  const response = await getStudentLearningAnalytics(courseId.value, studentId)
  studentDetail.value = response?.data ?? response
}

onMounted(load)
</script>

<template>
  <div class="sfx-page sfx-analytics-page">
    <SfxSkeleton v-if="state === 'loading'" :lines="5" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />
    <template v-else>
      <header class="sfx-page-head">
        <div>
          <p class="sfx-t-kicker">LEARNING ANALYTICS</p>
          <h1 class="sfx-t-title2">学习进度与认知分析</h1>
          <p class="sfx-t-secondary">按当前发布版本统计知识点学习状态；掌握结论仅来自正式证据。</p>
        </div>
        <div class="sfx-analytics-summary">
          <strong>{{ analytics?.student_count || 0 }}</strong><span>名学生</span>
          <strong>{{ points.length }}</strong><span>个知识点</span>
        </div>
      </header>
      <section class="sfx-panel">
        <h2 class="sfx-panel-title">知识点完成情况</h2>
        <div class="sfx-table-wrap">
          <table class="sfx-table">
            <thead><tr><th>知识点</th><th>未开始</th><th>学习中</th><th>已完成</th><th>完成率</th><th>掌握/置信</th><th>待干预</th></tr></thead>
            <tbody>
              <tr v-for="point in points" :key="point.outline_node_id">
                <td>{{ point.title }}</td><td>{{ point.not_started }}</td><td>{{ point.in_progress }}</td><td>{{ point.completed }}</td><td>{{ Math.round(point.completion_rate * 100) }}%</td>
                <td>{{ point.unknown_mastery_count }} 未知 / {{ point.low_confidence_count }} 低置信</td>
                <td>{{ point.pending_recommendation_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <section class="sfx-panel">
        <h2 class="sfx-panel-title">学生下钻</h2>
        <div class="sfx-analytics-students">
          <div v-for="student in students" :key="student.student_id" class="sfx-analytics-student-row">
            <span>学生 {{ student.student_id }}</span>
            <span>{{ student.completed }} / {{ student.total }} 已完成</span>
            <span>{{ Math.round(student.completion_rate * 100) }}%</span>
            <SfxButton size="sm" variant="secondary" @click="inspectStudent(student.student_id)">查看矩阵</SfxButton>
          </div>
          <p v-if="!students.length" class="sfx-t-secondary">当前发布版本没有可统计的学生。</p>
        </div>
      </section>
      <section v-if="studentDetail" class="sfx-panel">
        <h2 class="sfx-panel-title">学生 {{ selectedStudent }} 学习明细</h2>
        <div v-for="item in studentDetail.items" :key="item.outline_node_id" class="sfx-analytics-student-row">
          <span>{{ item.title }}</span><span>{{ item.learning.status }}</span><span>{{ Math.round(item.learning.completion_ratio * 100) }}%</span><span>{{ item.cognition.mastery_level || item.cognition.status }}</span>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.sfx-analytics-summary { display:flex; gap:8px; align-items:baseline; color:var(--text-secondary); }
.sfx-analytics-summary strong { font-size:24px; color:var(--text-primary); margin-left:16px; }
.sfx-table-wrap { overflow:auto; }
.sfx-table { width:100%; border-collapse:collapse; }
.sfx-table th,.sfx-table td { padding:12px 10px; border-bottom:1px solid var(--border-default); text-align:left; }
.sfx-analytics-student-row { display:grid; grid-template-columns:2fr 1fr 1fr 1fr; padding:10px 0; border-bottom:1px solid var(--border-subtle); }
</style>
