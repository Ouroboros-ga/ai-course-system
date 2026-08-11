<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Compass, Search } from 'lucide-vue-next'
import { listFacadeCourses } from '@/api/facade.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxDrawer from '@/app/ui/SfxDrawer.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 课程大厅（page-design §9.3）。
 * 数据源：GET /document/courses（available；学生只见已发布，教师另见自己的课）。
 * 大厅仅展示「已发布」课程用于发现（契约 §3.2：不可泄露草稿课）。
 * 加入方式：邀请码（available）；申请审核为 planned，如实标注。
 */
const router = useRouter()
const coursesContext = inject('coursesContext', null)

const status = ref('loading')
const courses = ref([])
const keyword = ref('')
const teacherFilter = ref('')

const detailCourse = ref(null)

const filtered = computed(() => {
  let list = courses.value
  const kw = keyword.value.trim().toLowerCase()
  if (kw) {
    list = list.filter((c) =>
      (c.title || '').toLowerCase().includes(kw) || (c.description || '').toLowerCase().includes(kw),
    )
  }
  const tw = teacherFilter.value.trim().toLowerCase()
  if (tw) list = list.filter((c) => (c.teacher_name || '').toLowerCase().includes(tw))
  return list
})

async function load() {
  status.value = 'loading'
  try {
    const data = await listFacadeCourses('hall')
    courses.value = Array.isArray(data?.items) ? data.items : []
    status.value = courses.value.length ? 'ready' : 'empty'
  } catch {
    status.value = 'error'
  }
}

function openDetail(course) {
  detailCourse.value = course
}

function closeDetail() {
  detailCourse.value = null
}

function joinFromHall() {
  closeDetail()
  coursesContext?.openJoin?.()
}

/**
 * CourseCard 门面层的稳定公开标识是 course_id；保留 id 只是为了兼容
 * 早期本地 fixture。课程大厅绝不能从全局用户角色或 teacher_id 推断访问权。
 */
function courseIdOf(course) {
  return course?.course_id ?? course?.id ?? null
}

function isJoined(course) {
  return course?.access?.joined === true
}

function enterCourse(course) {
  const courseId = courseIdOf(course)
  if (!courseId) return
  closeDetail()
  router.push(`/app/course/${courseId}/overview`)
}

function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('zh-CN')
}

onMounted(load)
</script>

<template>
  <div class="sfx-page">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">课程大厅</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">发现已发布的课程，查看加入条件</p>
      </div>
    </header>

    <div v-if="status === 'ready'" class="sfx-toolbar" role="search">
      <div class="sfx-hall-search">
        <Search :size="15" aria-hidden="true" />
        <input v-model="keyword" class="sfx-hall-search-input" placeholder="搜索课程名称或简介" aria-label="搜索课程" />
      </div>
      <input
        v-model="teacherFilter"
        class="sfx-input sfx-input--sm"
        placeholder="按教师筛选"
        aria-label="按教师筛选"
      />
    </div>

    <SfxSkeleton v-if="status === 'loading'" :lines="4" block />

    <SfxError v-else-if="status === 'error'" description="课程大厅暂时无法读取，请稍后重试。" @retry="load" />

    <SfxEmpty
      v-else-if="status === 'empty'"
      title="暂时没有已发布的课程"
      description="课程发布后才会出现在大厅。你也可以通过教师提供的邀请码直接加入课程。"
    >
      <template #icon><Compass :size="28" :stroke-width="1.8" /></template>
      <SfxButton variant="primary" size="sm" @click="joinFromHall">输入邀请码加入</SfxButton>
    </SfxEmpty>

    <template v-else>
      <p v-if="!filtered.length" class="sfx-hall-empty sfx-t-ui sfx-t-secondary">没有符合条件的课程</p>

      <div v-else class="sfx-hall-grid">
        <article
          v-for="course in filtered"
          :key="course.id"
          class="sfx-hall-card"
          tabindex="0"
          @click="openDetail(course)"
          @keydown.enter="openDetail(course)"
        >
          <div class="sfx-hall-card-head">
            <h2 class="sfx-t-title3">{{ course.title }}</h2>
            <SfxBadge v-if="course.access?.joined" tone="ink">已加入</SfxBadge>
          </div>
          <p class="sfx-hall-card-teacher sfx-t-caption">{{ course.teacher_name || '未知教师' }}</p>
          <p class="sfx-hall-card-desc sfx-t-ui sfx-t-secondary">{{ course.description || '该课程暂未填写简介。' }}</p>
          <div class="sfx-hall-card-meta sfx-t-caption">
            <span>{{ course.access?.join_method === 'invite_code' ? '需邀请码' : '可申请加入' }}</span>
            <span>最近活动 {{ formatDate(course.last_activity_at) }}</span>
          </div>
          <div class="sfx-hall-card-foot">
            <SfxButton
              variant="tertiary"
              size="sm"
              :aria-label="`${course.title}：${course.access?.joined ? '查看课程状态' : '查看加入方式'}`"
              @click.stop="openDetail(course)"
            >{{ course.access?.joined ? '已加入' : '查看加入方式' }}</SfxButton>
            <SfxButton variant="secondary" size="sm" @click.stop="openDetail(course)">查看详情</SfxButton>
          </div>
        </article>
      </div>
    </template>

    <!-- 课程详情抽屉（§9.3） -->
    <SfxDrawer :open="Boolean(detailCourse)" :title="detailCourse?.title || '课程详情'" :width="480" @close="closeDetail">
      <template v-if="detailCourse">
        <dl class="sfx-desc">
          <dt>授课教师</dt><dd>{{ detailCourse.teacher_name || '未知教师' }}</dd>
          <dt>开课时间</dt><dd>{{ formatDate(detailCourse.created_at) }}</dd>
          <dt>知识点</dt><dd>{{ detailCourse.total_nodes ?? 0 }} 个</dd>
          <dt>当前人数</dt><dd>{{ detailCourse.student_count ?? 0 }} 名学生</dd>
          <dt>课程来源</dt><dd>{{ detailCourse.is_ai_generated ? 'AI 辅助建设' : '教师建设' }}</dd>
        </dl>

        <section>
          <h3 class="sfx-t-ui sfx-hall-drawer-heading">课程简介</h3>
          <p class="sfx-t-body sfx-t-secondary">{{ detailCourse.description || '该课程暂未填写简介。' }}</p>
        </section>

        <section>
          <h3 class="sfx-t-ui sfx-hall-drawer-heading">加入规则</h3>
          <p class="sfx-t-ui sfx-t-secondary">
            当前可通过邀请码加入课程。如需申请加入，请联系教师获取邀请码。
          </p>
        </section>
      </template>

      <template #footer>
        <SfxButton variant="tertiary" @click="closeDetail">关闭</SfxButton>
        <SfxButton
          v-if="detailCourse && isJoined(detailCourse)"
          variant="primary"
          @click="enterCourse(detailCourse)"
        >进入课程</SfxButton>
        <SfxButton v-else variant="primary" @click="joinFromHall">输入邀请码加入</SfxButton>
      </template>
    </SfxDrawer>
  </div>
</template>

<style scoped>
.sfx-hall-search {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: var(--control-height);
  padding: 0 var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-panel);
  color: var(--text-muted);
  min-width: 280px;
}

.sfx-hall-search-input {
  border: none;
  outline: none;
  background: transparent;
  font-size: var(--ui-md-size);
  color: var(--text-primary);
  width: 100%;
}

.sfx-hall-empty { padding: var(--space-8) 0; text-align: center; }

.sfx-hall-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--space-4);
}

.sfx-hall-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
}

.sfx-hall-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-xs);
}

.sfx-hall-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.sfx-hall-card-desc {
  flex: 1;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  min-height: 60px;
}

.sfx-hall-card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}

.sfx-hall-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-top: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-subtle);
}

.sfx-hall-drawer-heading {
  color: var(--text-primary);
  margin-bottom: var(--space-2);
}
</style>
