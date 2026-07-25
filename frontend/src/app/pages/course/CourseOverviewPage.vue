<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, BookOpenCheck, FileText, Layers3, Timer, CheckCircle2, ListTodo, MessageSquareText } from 'lucide-vue-next'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import { getCourseDashboard } from '@/api/dashboard.js'

const router = useRouter()
const { course, courseRole, courseId } = inject('courseContext')

const detail = computed(() => course.value ?? {})

// 批次1：课程概览真实待办
const dashboard = ref(null)
const dashboardError = ref('')
const dashboardLoading = ref(false)

const continueInfo = computed(() => dashboard.value?.continue ?? null)
const progressInfo = computed(() => dashboard.value?.progress ?? null)
const pendingItems = computed(() => dashboard.value?.pending ?? [])
const recentResponses = computed(() => dashboard.value?.recent_responses ?? [])

async function loadDashboard() {
  dashboardLoading.value = true
  dashboardError.value = ''
  try {
    dashboard.value = await getCourseDashboard(courseId)
  } catch (e) {
    dashboardError.value = e?.message || '概览数据加载失败'
  } finally {
    dashboardLoading.value = false
  }
}

onMounted(() => {
  loadDashboard()
})

function formatDuration(seconds) {
  const value = Number(seconds) || 0
  if (!value) return '时长未知'
  const minutes = Math.round(value / 60)
  if (minutes < 60) return `约 ${minutes} 分钟`
  return `约 ${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`
}

function formatPercent(rate) {
  const v = Number(rate) || 0
  return Math.round(v * 100) + '%'
}
</script>

<template>
  <div class="sfx-overview">
    <!-- A. 继续学习（page-design §11.1 A）：当前课程与主操作 -->
    <section class="sfx-overview-hero">
      <div class="sfx-overview-hero-main">
        <h1 class="sfx-t-title1">{{ detail.title }}</h1>
        <p v-if="detail.description" class="sfx-t-body sfx-t-secondary sfx-overview-desc">
          {{ detail.description }}
        </p>
        <div class="sfx-overview-meta sfx-t-caption">
          <span><Layers3 :size="13" /> {{ detail.total_nodes ?? '-' }} 个知识点</span>
          <span><Timer :size="13" /> {{ formatDuration(detail.total_duration) }}</span>
          <span><FileText :size="13" /> {{ detail.total_pages ?? '-' }} 页资料</span>
          <SfxBadge :tone="detail.status === 'published' ? 'green' : 'amber'">
            {{ detail.status === 'published' ? '已发布' : '草稿' }}
          </SfxBadge>
        </div>
        <!-- 批次1：继续学习位置 -->
        <p v-if="continueInfo" class="sfx-t-caption sfx-overview-continue">
          上次学到：{{ continueInfo.node_title || '知识点 ' + (continueInfo.node_index ?? '?') }} · 第 {{ continueInfo.page ?? 1 }} 页
        </p>
      </div>
      <SfxButton variant="primary" @click="router.push(`/app/course/${courseId}/learn`)">
        {{ courseRole === 'teacher' ? '学生视角预览' : '继续学习' }}
        <template #icon><ArrowRight :size="16" /></template>
      </SfxButton>
    </section>

    <!-- B. 学习进度（真实数据，不伪造） -->
    <section class="sfx-overview-section">
      <h2 class="sfx-t-title2 sfx-overview-section-title">
        <CheckCircle2 :size="20" /> 学习进度
      </h2>
      <div v-if="dashboardLoading" class="sfx-t-caption">加载中…</div>
      <div v-else-if="progressInfo" class="sfx-overview-progress">
        <div class="sfx-overview-progress-bar">
          <div class="sfx-overview-progress-fill" :style="{ width: formatPercent(progressInfo.completion_rate) }"></div>
        </div>
        <dl class="sfx-overview-facts">
          <div class="sfx-overview-fact">
            <dt class="sfx-t-caption">完成进度</dt>
            <dd class="sfx-t-ui">{{ formatPercent(progressInfo.completion_rate) }}</dd>
          </div>
          <div class="sfx-overview-fact">
            <dt class="sfx-t-caption">已完成节点</dt>
            <dd class="sfx-t-ui">{{ progressInfo.completed_nodes ?? 0 }} / {{ progressInfo.total_nodes ?? detail.total_nodes ?? '-' }}</dd>
          </div>
          <div v-if="progressInfo.current_chapter" class="sfx-overview-fact">
            <dt class="sfx-t-caption">当前章节</dt>
            <dd class="sfx-t-ui">{{ progressInfo.current_chapter }}</dd>
          </div>
        </dl>
      </div>
      <p v-else class="sfx-t-caption">尚无学习进度记录，开始学习后将显示。</p>
    </section>

    <!-- C. 当前待办（前置知识跳转未返回） -->
    <section class="sfx-overview-section">
      <h2 class="sfx-t-title2 sfx-overview-section-title">
        <ListTodo :size="20" /> 当前待办
      </h2>
      <div v-if="dashboardLoading" class="sfx-t-caption">加载中…</div>
      <ul v-else-if="pendingItems.length" class="sfx-overview-pending">
        <li v-for="(item, i) in pendingItems" :key="i" class="sfx-overview-pending-item">
          <span class="sfx-overview-pending-type">{{ item.type === 'prerequisite_jump' ? '前置知识回顾' : item.type }}</span>
          <span class="sfx-t-ui">{{ item.title }}</span>
        </li>
      </ul>
      <p v-else class="sfx-t-caption">暂无待办事项。</p>
    </section>

    <!-- D. 最近课程回应（理解度分析） -->
    <section class="sfx-overview-section">
      <h2 class="sfx-t-title2 sfx-overview-section-title">
        <MessageSquareText :size="20" /> 最近课程回应
      </h2>
      <div v-if="dashboardLoading" class="sfx-t-caption">加载中…</div>
      <ul v-else-if="recentResponses.length" class="sfx-overview-responses">
        <li v-for="(item, i) in recentResponses" :key="i" class="sfx-overview-response">
          <p class="sfx-t-ui sfx-overview-response-obs">{{ item.observation }}</p>
          <p v-if="item.suggestion" class="sfx-t-caption sfx-overview-response-sug">{{ item.suggestion }}</p>
        </li>
      </ul>
      <p v-else class="sfx-t-caption">尚无课程回应记录，学习中提问后将显示。</p>
    </section>

    <!-- E. 课程信息 -->
    <section class="sfx-overview-section">
      <h2 class="sfx-t-title2 sfx-overview-section-title">
        <BookOpenCheck :size="20" /> 课程信息
      </h2>
      <dl class="sfx-overview-facts">
        <div class="sfx-overview-fact">
          <dt class="sfx-t-caption">课程编号</dt>
          <dd class="sfx-t-ui sfx-mono">{{ detail.id }}</dd>
        </div>
        <div class="sfx-overview-fact">
          <dt class="sfx-t-caption">来源资料</dt>
          <dd class="sfx-t-ui">{{ detail.source_file_name || '未记录' }}</dd>
        </div>
        <div class="sfx-overview-fact">
          <dt class="sfx-t-caption">创建时间</dt>
          <dd class="sfx-t-ui">{{ detail.created_at ? new Date(detail.created_at).toLocaleDateString('zh-CN') : '未知' }}</dd>
        </div>
      </dl>
    </section>
  </div>
</template>

<style scoped>
.sfx-overview {
  max-width: 960px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-6) var(--space-16);
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
}

.sfx-overview-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-6);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-8);
}

.sfx-overview-hero-main {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-width: 0;
}

.sfx-overview-desc {
  max-width: 640px;
}

.sfx-overview-continue {
  color: var(--text-secondary, #666);
}

.sfx-overview-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-4);
}

.sfx-overview-meta span {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.sfx-overview-section {
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
}

.sfx-overview-section-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}

.sfx-overview-progress-bar {
  height: 8px;
  background: var(--surface-muted, #f0f0f0);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: var(--space-4);
}

.sfx-overview-progress-fill {
  height: 100%;
  background: var(--accent-primary, #4f8cf7);
  border-radius: 4px;
  transition: width var(--duration-normal) var(--ease-out);
}

.sfx-overview-facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-4);
  margin: 0;
}

.sfx-overview-fact dt {
  margin-bottom: var(--space-1);
}

.sfx-overview-fact dd {
  margin: 0;
  color: var(--text-primary);
}

.sfx-overview-pending {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sfx-overview-pending-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-muted, #fafafa);
  border-radius: var(--radius-sm, 4px);
}

.sfx-overview-pending-type {
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: 4px;
  background: #fff3e0;
  color: #e65100;
  white-space: nowrap;
}

.sfx-overview-responses {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sfx-overview-response {
  padding: var(--space-3);
  background: var(--surface-muted, #fafafa);
  border-radius: var(--radius-sm, 4px);
}

.sfx-overview-response-obs {
  margin: 0 0 4px 0;
}

.sfx-overview-response-sug {
  margin: 0;
  color: var(--text-secondary, #666);
}
</style>
