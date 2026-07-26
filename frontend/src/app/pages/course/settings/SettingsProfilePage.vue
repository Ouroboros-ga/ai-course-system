<script setup>
import { computed, inject } from 'vue'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 设置 · 基础信息（page-design §18.2）。
 * 只读信息来自课程详情真实响应；编辑写模型
 * PUT /course-settings/course/{id}/profile 为 planned 契约，不提供假表单。
 */
const courseContext = inject('courseContext')

const course = computed(() => courseContext.course.value)
const detail = computed(() => courseContext.detail.value)

const statusMeta = {
  draft: { label: '草稿', tone: 'amber' },
  published: { label: '已发布', tone: 'green' },
  archived: { label: '已归档', tone: 'neutral' },
  closed: { label: '已关闭', tone: 'red' },
}

const rows = computed(() => {
  const c = course.value ?? {}
  return [
    { label: '课程名称', value: c.title },
    { label: '课程简介', value: c.description || '未填写' },
    { label: '知识点数', value: c.total_nodes != null ? `${c.total_nodes} 个` : '—' },
    { label: '预计总时长', value: c.total_duration != null ? `${c.total_duration} 分钟` : '—' },
    { label: '源文件', value: c.source_file_name || '—' },
    { label: '建设方式', value: c.is_ai_generated ? 'AI 辅助建设' : '教师建设' },
  ]
})

const readonlyRows = computed(() => {
  const c = course.value ?? {}
  return [
    { label: '课程 ID', value: c.id != null ? `#${c.id}` : '—' },
    { label: '创建时间', value: c.created_at ? new Date(c.created_at).toLocaleString('zh-CN') : '—' },
    { label: '激活脚本', value: detail.value?.script?.id != null ? `脚本 #${detail.value.script.id}` : '—' },
  ]
})
</script>

<template>
  <div class="sfx-profile">
    <header class="sfx-profile-head">
      <div>
        <h1 class="sfx-t-title2">基础信息</h1>
        <p class="sfx-t-ui sfx-t-secondary">课程名称、简介与基本属性</p>
      </div>
      <SfxBadge :tone="statusMeta[course?.status]?.tone ?? 'neutral'">
        {{ statusMeta[course?.status]?.label ?? course?.status }}
      </SfxBadge>
    </header>

    <section class="sfx-panel">
      <dl class="sfx-desc">
        <template v-for="row in rows" :key="row.label">
          <dt>{{ row.label }}</dt><dd>{{ row.value }}</dd>
        </template>
      </dl>
    </section>

    <section class="sfx-panel">
      <h2 class="sfx-panel-title">系统信息（只读）</h2>
      <dl class="sfx-desc">
        <template v-for="row in readonlyRows" :key="row.label">
          <dt>{{ row.label }}</dt><dd class="sfx-mono">{{ row.value }}</dd>
        </template>
      </dl>
    </section>

    <SfxPlannedPanel
      contract-key="course-settings"
      title="基础信息编辑 · 接口契约已冻结"
      available-note="上方全部字段为课程详情真实数据。"
    />
  </div>
</template>

<style scoped>
.sfx-profile {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-6);
  max-width: 860px;
}

.sfx-profile-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
}
</style>
