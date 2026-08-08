<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, BookOpen } from 'lucide-vue-next'
import { getMyCourses } from '@/api/courses.js'
import { useCounterStore } from '@/stores/counter.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'
import ParticleBackground from '@/components/home/ui/ParticleBackground.vue'

const router = useRouter()
const counter = useCounterStore()

const loading = ref(true)
const courses = ref([])

// page-design §8.2 第一优先级：最近中断且可继续的学习。
// 「需要处理」「系统回应」依赖后端尚不存在的聚合端点，本切片不渲染
// （§8.3：禁止展示没有可执行动作的内容）。
const recentCourses = computed(() =>
  [...courses.value]
    .sort((a, b) => new Date(b.last_study_time || 0) - new Date(a.last_study_time || 0))
    .slice(0, 3)
)

onMounted(async () => {
  try {
    const data = await getMyCourses()
    courses.value = Array.isArray(data?.courses) ? data.courses : []
  } catch {
    // 教师/管理员无学生课程列表（后端 403）：首页按「无继续学习」呈现，
    // 这是真实状态而非错误。
    courses.value = []
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="sfx-home-root">
    <ParticleBackground class="sfx-home-particles" />
    <div class="sfx-home">
      <header class="sfx-home-header">
        <h1 class="sfx-t-title1">{{ counter.displayName ? `${counter.displayName}，欢迎回来` : '工作首页' }}</h1>
        <p class="sfx-t-ui sfx-t-secondary">继续你中断的学习</p>
      </header>

      <section aria-label="继续进行">
        <h2 class="sfx-t-title2 sfx-home-section-title">继续进行</h2>

        <SfxSkeleton v-if="loading" :lines="3" />

        <SfxEmpty
          v-else-if="!recentCourses.length"
          title="当前没有可继续的学习"
          description="加入课程后，最近的学习进度会出现在这里。"
        >
          <template #icon><BookOpen :size="28" :stroke-width="1.8" /></template>
          <SfxButton variant="secondary" size="sm" @click="router.push('/app/courses/learning')">
            前往我的课程
          </SfxButton>
        </SfxEmpty>

        <ul v-else class="sfx-home-continue">
          <li v-for="course in recentCourses" :key="course.enrollment_id" class="sfx-home-item">
            <div class="sfx-home-item-main">
              <span class="sfx-t-title3">{{ course.title }}</span>
              <span class="sfx-t-caption">进度 {{ Math.round(course.overall_progress || 0) }}% · {{ course.teacher_name || '未知教师' }}</span>
            </div>
            <SfxButton variant="primary" size="sm" @click="router.push(`/app/course/${course.course_id}/learn`)">
              继续学习
              <template #icon><ArrowRight :size="15" /></template>
            </SfxButton>
          </li>
        </ul>

        <div class="sfx-home-more">
          <RouterLink to="/app/courses/learning" class="sfx-t-ui">查看全部课程</RouterLink>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
/* 根容器：撑满 main 滚动区，作为粒子画布的定位上下文 */
.sfx-home-root {
  position: relative;
  flex: 1;
  width: 100%;
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

/* 粒子背景层：覆盖整个首页内容区，置于内容之下 */
.sfx-home-particles {
  position: absolute;
  inset: 0;
  z-index: 0;
}

.sfx-home {
  position: relative;
  z-index: 1;
  max-width: 960px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-6) var(--space-16);
  width: 100%;
}

.sfx-home-header {
  margin-bottom: var(--space-8);
}

.sfx-home-section-title {
  margin-bottom: var(--space-4);
}

.sfx-home-continue {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sfx-home-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-4) var(--space-6);
}

.sfx-home-item-main {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}

.sfx-home-more {
  margin-top: var(--space-4);
}
</style>
