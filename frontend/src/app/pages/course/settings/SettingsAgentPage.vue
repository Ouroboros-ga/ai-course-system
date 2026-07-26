<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { getCourseCapabilities } from '@/api/course_access.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 设置 · 智能体（page-design §18.4）。
 * 真实呈现：课程能力上下文（capabilities/allowed，available）。
 * 智能体策略写模型（回答范围、必须引用、提示层级、自定义说明等）
 * PUT /course-settings/course/{id}/agent-policy 为 planned 契约（§3.8）。
 * 纪律：禁止教师直接修改平台底层系统提示词全文（§18.4）。
 */
const route = useRoute()
const courseId = Number(route.params.courseId)

const status = ref('loading')
const caps = ref(null)

const allowedLabel = {
  course_building: '课程建设',
  knowledge_graph: '知识图谱',
  experiment: '实验运行',
  analytics: '课程学情',
}

async function load() {
  status.value = 'loading'
  try {
    caps.value = await getCourseCapabilities(courseId)
    status.value = 'ready'
  } catch {
    status.value = 'error'
  }
}

onMounted(load)
</script>

<template>
  <div class="sfx-agent">
    <header class="sfx-agent-head">
      <div>
        <h1 class="sfx-t-title2">智能体</h1>
        <p class="sfx-t-ui sfx-t-secondary">课程智能体的能力与行为边界</p>
      </div>
    </header>

    <section class="sfx-panel">
      <h2 class="sfx-panel-title">当前能力上下文（真实）</h2>
      <SfxSkeleton v-if="status === 'loading'" :lines="3" />
      <SfxError v-else-if="status === 'error'" title="能力信息读取失败" description="课程能力上下文暂时无法读取。" @retry="load" />
      <dl v-else class="sfx-desc">
        <dt>当前课程角色</dt>
        <dd>{{ caps?.course_role ?? '—' }}</dd>
        <dt>可用能力域</dt>
        <dd>
          <span class="sfx-agent-allowed">
            <SfxBadge
              v-for="(label, key) in allowedLabel"
              :key="key"
              :tone="caps?.allowed?.[key] ? 'green' : 'neutral'"
            >{{ label }}{{ caps?.allowed?.[key] ? '' : '（未开启）' }}</SfxBadge>
          </span>
        </dd>
        <dt>能力明细</dt>
        <dd>
          <code v-if="caps?.capabilities && Object.keys(caps.capabilities).length" class="sfx-agent-caps sfx-mono">{{ JSON.stringify(caps.capabilities, null, 2) }}</code>
          <span v-else>后端未返回额外能力开关</span>
        </dd>
      </dl>
    </section>

    <SfxPlannedPanel
      contract-key="course-settings"
      title="智能体策略配置 · 接口契约已冻结"
      available-note="课程能力上下文为真实数据；学习页的课程智能体已按此上下文运行。"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        契约实现后可配置（§18.4）：回答范围（仅课程 / 允许学科扩展）、是否必须原文引用、
        无依据时行为、允许的教学行动、提示层级策略与教师自定义说明。
        平台底层系统提示词全文不开放修改，只通过受控字段配置。
      </p>
    </SfxPlannedPanel>
  </div>
</template>

<style scoped>
.sfx-agent {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-6);
  max-width: 860px;
}

.sfx-agent-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
}

.sfx-agent-allowed {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.sfx-agent-caps {
  display: block;
  background: var(--surface-cool);
  border-radius: var(--radius-sm);
  padding: var(--space-3);
  font-size: var(--caption-size);
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
