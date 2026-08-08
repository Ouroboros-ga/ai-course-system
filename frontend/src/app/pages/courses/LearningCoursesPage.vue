<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { BookOpen, ChevronRight, Clock3, UserRound, LibraryBig } from 'lucide-vue-next'
import { listFacadeCourses } from '@/api/facade.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const router = useRouter()
const status = ref('loading') // loading | ready | empty | error
const courses = ref([])

function formatLastStudy(iso) {
  if (!iso) return '尚未开始学习'
  const time = new Date(iso)
  if (Number.isNaN(time.getTime())) return '尚未开始学习'
  const diffDays = Math.floor((Date.now() - time.getTime()) / 86400000)
  if (diffDays <= 0) return '今天学习过'
  if (diffDays === 1) return '昨天学习过'
  if (diffDays < 30) return `${diffDays} 天前学习过`
  return time.toLocaleDateString('zh-CN')
}

async function load() {
  status.value = 'loading'
  try {
    const data = await listFacadeCourses('learning')
    courses.value = Array.isArray(data?.items) ? data.items : []
    status.value = courses.value.length ? 'ready' : 'empty'
  } catch (e) {
    status.value = 'error'
  }
}

function continueCourse(course) {
  router.push(`/app/course/${course.course_id}/learn`)
}

function openOverview(course) {
  router.push(`/app/course/${course.course_id}/overview`)
}

function openResearch(course) {
  router.push(`/app/course/${course.course_id}/research`)
}

onMounted(load)
</script>

<template>
  <div class="sfx-courses">
    <header class="sfx-courses-header">
      <div>
        <h1 class="sfx-t-title1">我学习的</h1>
        <p class="sfx-t-ui sfx-t-secondary">当前作为学生参与的课程</p>
      </div>
      <!-- §9.1 主操作「加入课程」已上收到 CoursesLayout 的 L2 导航右侧（§4.3）。 -->
    </header>

    <SfxSkeleton v-if="status === 'loading'" :lines="4" block />

    <SfxError
      v-else-if="status === 'error'"
      description="课程列表暂时无法读取，请稍后重试。"
      @retry="load"
    />

    <SfxEmpty
      v-else-if="status === 'empty'"
      title="你还没有加入任何课程"
      description="加入课程后会在这里显示学习进度和上次学习位置。邀请码加入与课程大厅将在后续版本提供。"
    >
      <template #icon><BookOpen :size="28" :stroke-width="1.8" /></template>
    </SfxEmpty>

    <ul v-else class="sfx-course-list">
      <li
        v-for="course in courses"
        :key="course.course_id"
        class="sfx-course-card"
        tabindex="0"
        @click="openOverview(course)"
        @keydown.enter="openOverview(course)"
      >
        <div class="sfx-course-main">
          <div class="sfx-course-title-row">
            <h2 class="sfx-t-title3">{{ course.title }}</h2>
            <SfxBadge tone="ink">学生</SfxBadge>
          </div>
          <p class="sfx-course-teacher sfx-t-caption">
            <UserRound :size="13" /> {{ course.teacher_name || '未知教师' }}
          </p>

          <div class="sfx-course-progress" role="progressbar"
               :aria-valuenow="Math.round((course.progress?.overall_progress || 0) * 100)" aria-valuemin="0" aria-valuemax="100"
               :aria-label="`学习进度 ${Math.round((course.progress?.overall_progress || 0) * 100)}%`">
            <div class="sfx-course-progress-bar" :style="{ width: `${Math.min(100, (course.progress?.overall_progress || 0) * 100)}%` }" />
          </div>

          <div class="sfx-course-meta sfx-t-caption">
            <span>进度 {{ Math.round((course.progress?.overall_progress || 0) * 100) }}%</span>
            <span>{{ course.progress?.total_nodes ?? '—' }} 个知识点</span>
            <span><Clock3 :size="12" /> {{ formatLastStudy(course.progress?.last_study_time) }}</span>
          </div>
        </div>

        <div class="sfx-course-actions">
          <SfxButton variant="secondary" size="sm" @click.stop="openResearch(course)">
            科研工作台
            <template #icon><LibraryBig :size="15" /></template>
          </SfxButton>
          <SfxButton variant="primary" size="sm" @click.stop="continueCourse(course)">
            继续学习
            <template #icon><ChevronRight :size="15" /></template>
          </SfxButton>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.sfx-courses {
  max-width: 960px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-6) var(--space-16);
  width: 100%;
}

.sfx-courses-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.sfx-course-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.sfx-course-card {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
}

.sfx-course-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-xs);
}

.sfx-course-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.sfx-course-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.sfx-course-teacher {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.sfx-course-progress {
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--surface-soft);
  overflow: hidden;
  margin-top: var(--space-1);
}

.sfx-course-progress-bar {
  height: 100%;
  border-radius: var(--radius-full);
  background: var(--green-500);
  transition: width var(--duration-slow) var(--ease-out);
}

.sfx-course-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
}

.sfx-course-meta span {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.sfx-course-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

@media (max-width: 720px) {
  .sfx-course-card { align-items: stretch; flex-direction: column; }
  .sfx-course-actions { justify-content: flex-end; }
}
</style>
