<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Hammer, Search } from 'lucide-vue-next'
import { listFacadeCourses } from '@/api/facade.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 我建设的（page-design §9.2）。
 *
 * 数据源（adapter 标注）：GET /document/courses 返回「自己创建的全部课程 +
 * 其他教师的已发布课程」，本页按 teacher_id === 当前用户 过滤出建设中的课程。
 * API 契约 §3.2 的 GET /facade/courses?view=building 落地后切换，字段口径不变。
 *
 * 零伪造：待确认候选数 / 失败任务数需要按课程聚合读模型（planned），本页不
 * 展示推测数字；建设阶段以课程真实 status 呈现。
 */
const router = useRouter()

const status = ref('loading') // loading | ready | empty | error
const courses = ref([])
const keyword = ref('')
const statusFilter = ref('all') // all | draft | published | archived
const sortBy = ref('recent') // recent | name

const statusMeta = {
  draft: { label: '草稿', tone: 'amber' },
  published: { label: '已发布', tone: 'green' },
  archived: { label: '已归档', tone: 'neutral' },
  closed: { label: '已关闭', tone: 'red' },
}

const filtered = computed(() => {
  let list = courses.value
  const kw = keyword.value.trim().toLowerCase()
  if (kw) list = list.filter((c) => (c.title || '').toLowerCase().includes(kw))
  if (statusFilter.value !== 'all') list = list.filter((c) => c.status === statusFilter.value)
  if (sortBy.value === 'name') {
    list = [...list].sort((a, b) => String(a.title).localeCompare(String(b.title), 'zh-CN'))
  }
  return list
})

async function load() {
  status.value = 'loading'
  try {
    const data = await listFacadeCourses('building')
    courses.value = Array.isArray(data?.items) ? data.items : []
    status.value = courses.value.length ? 'ready' : 'empty'
  } catch {
    status.value = 'error'
  }
}

function continueBuild(course) {
  router.push(`/app/course/${course.course_id}/build`)
}

function openOverview(course) {
  router.push(`/app/course/${course.course_id}/overview`)
}

function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('zh-CN')
}

onMounted(load)
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">我建设的</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">作为教师建设或共同建设的课程</p>
      </div>
      <!-- 主操作「创建课程」位于「我的课程」L2 顶栏，任何登录用户均可创建 -->
    </header>

    <div v-if="status === 'ready'" class="sfx-toolbar" role="search">
      <div class="sfx-toolbar-search">
        <Search :size="15" aria-hidden="true" />
        <input v-model="keyword" class="sfx-toolbar-input" placeholder="搜索课程名称" aria-label="搜索课程名称" />
      </div>
      <select v-model="statusFilter" class="sfx-select sfx-toolbar-select" aria-label="按状态筛选">
        <option value="all">全部状态</option>
        <option value="draft">草稿</option>
        <option value="published">已发布</option>
        <option value="archived">已归档</option>
      </select>
      <select v-model="sortBy" class="sfx-select sfx-toolbar-select" aria-label="排序方式">
        <option value="recent">最近创建</option>
        <option value="name">课程名称</option>
      </select>
    </div>

    <SfxSkeleton v-if="status === 'loading'" :lines="4" block />

    <SfxError
      v-else-if="status === 'error'"
      description="课程列表暂时无法读取，请稍后重试。"
      @retry="load"
    />

    <SfxEmpty
      v-else-if="status === 'empty'"
      title="你还没有建设中的课程"
      description="当前账号名下没有作为教师创建的课程。课程创建流程开放后，新建课程会出现在这里。"
    >
      <template #icon><Hammer :size="28" :stroke-width="1.8" /></template>
    </SfxEmpty>

    <template v-else>
      <p v-if="!filtered.length" class="sfx-filter-empty sfx-t-ui sfx-t-secondary">没有符合条件的课程</p>

      <ul v-else class="sfx-build-list">
        <li v-for="course in filtered" :key="course.course_id" class="sfx-build-card">
          <div class="sfx-build-main">
            <div class="sfx-build-title-row">
              <h2 class="sfx-t-title3">{{ course.title }}</h2>
              <SfxBadge tone="ink">教师</SfxBadge>
              <SfxBadge :tone="statusMeta[course.status]?.tone ?? 'neutral'">
                {{ statusMeta[course.status]?.label ?? course.status }}
              </SfxBadge>
            </div>
            <p v-if="course.description" class="sfx-t-ui sfx-t-secondary sfx-build-desc">{{ course.description }}</p>
            <div class="sfx-build-meta sfx-t-caption">
            <span>待审核 {{ course.build_status?.pending_review_count ?? 0 }} 项</span>
            <span v-if="course.build_status?.failed_task_count">失败任务 {{ course.build_status.failed_task_count }} 项</span>
            <span>最近活动 {{ formatDate(course.last_activity_at) }}</span>
            </div>
          </div>
          <div class="sfx-build-actions">
            <SfxButton variant="primary" size="sm" @click="continueBuild(course)">继续建设</SfxButton>
            <SfxButton variant="tertiary" size="sm" @click="openOverview(course)">课程概览</SfxButton>
          </div>
        </li>
      </ul>

      <p class="sfx-build-note sfx-t-caption">
        部分建设进度指标将在后续版本中展示。
      </p>
    </template>
  </div>
</template>

<style scoped>
.sfx-toolbar-search {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: var(--control-height);
  padding: 0 var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-panel);
  color: var(--text-muted);
  min-width: 240px;
}

.sfx-toolbar-input {
  border: none;
  outline: none;
  background: transparent;
  font-size: var(--ui-md-size);
  color: var(--text-primary);
  width: 100%;
}

.sfx-toolbar-select { width: auto; min-width: 120px; }

.sfx-filter-empty { padding: var(--space-8) 0; text-align: center; }

.sfx-build-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.sfx-build-card {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
}

.sfx-build-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-xs);
}

.sfx-build-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.sfx-build-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.sfx-build-desc {
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.sfx-build-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
}

.sfx-build-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.sfx-build-note {
  margin-top: var(--space-4);
  text-align: center;
}
</style>
