<script setup>
import { computed, inject } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, BookOpenCheck, FileText, Layers3, Timer } from 'lucide-vue-next'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const router = useRouter()
const { course, courseRole, courseId } = inject('courseContext')

const detail = computed(() => course.value ?? {})

function formatDuration(seconds) {
  const value = Number(seconds) || 0
  if (!value) return '时长未知'
  const minutes = Math.round(value / 60)
  if (minutes < 60) return `约 ${minutes} 分钟`
  return `约 ${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`
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
          <span><Layers3 :size="13" /> {{ detail.total_nodes ?? '—' }} 个知识点</span>
          <span><Timer :size="13" /> {{ formatDuration(detail.total_duration) }}</span>
          <span><FileText :size="13" /> {{ detail.total_pages ?? '—' }} 页资料</span>
          <SfxBadge :tone="detail.status === 'published' ? 'green' : 'amber'">
            {{ detail.status === 'published' ? '已发布' : '草稿' }}
          </SfxBadge>
        </div>
      </div>
      <SfxButton variant="primary" @click="router.push(`/app/course/${courseId}/learn`)">
        {{ courseRole === 'teacher' ? '学生视角预览' : '继续学习' }}
        <template #icon><ArrowRight :size="16" /></template>
      </SfxButton>
    </section>

    <!-- B. 课程信息（真实字段；进度/待办/学习信号依赖后续端点，不伪造） -->
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
      <p class="sfx-t-caption sfx-overview-note">
        学习进度明细、当前待办与最近课程回应将在后续切片接入真实数据后展示。
      </p>
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

.sfx-overview-note {
  margin-top: var(--space-4);
}
</style>
