<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { FlaskConical } from 'lucide-vue-next'
import { getSandboxHealth, getSandboxLanguages } from '@/api/sandbox.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxCapabilityTag from '@/app/ui/SfxCapabilityTag.vue'
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 课程实验任务（page-design §16）。
 *
 * 实验定义 / 尝试 / 评分 Evidence 为 planned 契约（§3.7）；
 * 沙箱运行能力为 available（GET /sandbox/health|languages）——本页真实探测并
 * 展示课程可用的语言与安全边界，不伪造实验任务列表。
 *
 * 学生视图：待完成｜进行中｜已完成（筛选器，非 Local Rail）。
 * 教师视图：任务列表 / 创建任务 / 提交情况（§16.2）。
 */
const courseContext = inject('courseContext')

const isTeacher = computed(() => Boolean(courseContext.allowed.value['course.edit']))

const studentFilter = ref('todo') // todo | doing | done
const teacherTab = ref('list') // list | create | submissions

const sandboxStatus = ref('loading') // loading | ready | error
const sandbox = ref(null)
const languages = ref([])

async function loadSandbox() {
  sandboxStatus.value = 'loading'
  try {
    const [health, langs] = await Promise.all([
      getSandboxHealth().catch(() => null),
      getSandboxLanguages().catch(() => null),
    ])
    sandbox.value = health
    languages.value = Array.isArray(langs?.languages) ? langs.languages : []
    sandboxStatus.value = 'ready'
  } catch {
    sandboxStatus.value = 'error'
  }
}

onMounted(loadSandbox)
</script>

<template>
  <div class="sfx-page">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">实验任务</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">
          {{ isTeacher ? '管理课程实验定义、查看提交情况' : '完成课程实验，运行记录会形成学习证据' }}
        </p>
      </div>
      <SfxCapabilityTag level="experimental" />
    </header>

    <!-- 沙箱运行能力（真实探测，available） -->
    <section class="sfx-panel">
      <div class="sfx-exp-sandbox-head">
        <h2 class="sfx-panel-title">代码沙箱</h2>
        <SfxBadge v-if="sandboxStatus === 'ready' && sandbox?.available" tone="green">运行能力可用</SfxBadge>
        <SfxBadge v-else-if="sandboxStatus === 'ready'" tone="amber">当前不可用</SfxBadge>
        <SfxBadge v-else tone="neutral">探测中</SfxBadge>
      </div>
      <template v-if="sandboxStatus === 'ready'">
        <dl class="sfx-desc">
          <dt>支持语言</dt>
          <dd>
            <span v-if="languages.length" class="sfx-exp-langs">
              <SfxBadge v-for="lang in languages" :key="lang" tone="ink">{{ lang }}</SfxBadge>
            </span>
            <span v-else>未获取到语言列表</span>
          </dd>
          <dt>能力边界</dt>
          <dd>当前提供「运行一段代码」的基础能力；完整实验流程（任务定义、尝试、测试评分）待实验契约实现。</dd>
        </dl>
      </template>
      <p v-else-if="sandboxStatus === 'error'" class="sfx-t-ui sfx-t-secondary">
        沙箱服务暂时不可达，实验运行不可用。这不影响课程其他内容。
      </p>
    </section>

    <!-- 学生视图 -->
    <template v-if="!isTeacher">
      <div class="sfx-exp-filters" role="tablist" aria-label="实验任务筛选">
        <button
          v-for="opt in [
            { value: 'todo', label: '待完成' },
            { value: 'doing', label: '进行中' },
            { value: 'done', label: '已完成' },
          ]"
          :key="opt.value"
          type="button"
          role="tab"
          :aria-selected="studentFilter === opt.value"
          class="sfx-exp-filter"
          :class="{ 'is-active': studentFilter === opt.value }"
          @click="studentFilter = opt.value"
        >{{ opt.label }}</button>
      </div>

      <SfxPlannedPanel
        contract-key="experiments"
        title="课程实验任务 · 接口契约已冻结"
        available-note="沙箱语言与安全边界已在上方真实展示；实验工作区将复用同一沙箱能力。"
      >
        <template #icon><FlaskConical :size="20" :stroke-width="1.9" /></template>
        <p class="sfx-t-ui sfx-t-secondary">
          教师发布实验任务后，这里会显示任务名称、关联知识点、截止时间与完成条件；
          完成实验后可查看学习记录与教师反馈。
        </p>
      </SfxPlannedPanel>
    </template>

    <!-- 教师视图 -->
    <template v-else>
      <div class="sfx-exp-filters" role="tablist" aria-label="教师实验工作区">
        <button
          v-for="opt in [
            { value: 'list', label: '任务列表' },
            { value: 'create', label: '创建任务' },
            { value: 'submissions', label: '提交情况' },
          ]"
          :key="opt.value"
          type="button"
          role="tab"
          :aria-selected="teacherTab === opt.value"
          class="sfx-exp-filter"
          :class="{ 'is-active': teacherTab === opt.value }"
          @click="teacherTab = opt.value"
        >{{ opt.label }}</button>
      </div>

      <SfxPlannedPanel
        v-if="teacherTab === 'list'"
        contract-key="experiments"
        title="实验任务列表 · 接口契约已冻结"
      >
        <p class="sfx-t-ui sfx-t-secondary">
          列表将包含：任务名、关联知识点、状态、截止时间、提交人数、异常数与安全策略（§16.2）。
        </p>
      </SfxPlannedPanel>

      <SfxPlannedPanel
        v-else-if="teacherTab === 'create'"
        contract-key="experiments"
        title="创建实验任务 · 接口契约已冻结"
      >
        <p class="sfx-t-ui sfx-t-secondary">
          创建流程按 §16.2 分为：基本信息 → 实验内容 → 评测与提示 → 安全策略 → 预览发布。
          沙箱预设与语言白名单已可在「设置 → 沙箱权限」中真实配置。
        </p>
      </SfxPlannedPanel>

      <SfxPlannedPanel
        v-else
        contract-key="experiments"
        title="提交情况 · 接口契约已冻结"
      >
        <p class="sfx-t-ui sfx-t-secondary">
          教师仅能查看课程任务范围内的证据（§16.2），不默认查看学生全部自主实验。
        </p>
      </SfxPlannedPanel>
    </template>
  </div>
</template>

<style scoped>
.sfx-exp-sandbox-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.sfx-exp-langs {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.sfx-exp-filters {
  display: inline-flex;
  gap: var(--space-1);
  background: var(--surface-soft);
  border-radius: var(--radius-md);
  padding: 3px;
  align-self: flex-start;
  margin: var(--space-2) 0 var(--space-2);
}

.sfx-exp-filter {
  height: 30px;
  padding: 0 var(--space-3);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: var(--ui-sm-size);
  font-weight: var(--ui-md-weight);
}

.sfx-exp-filter:hover { color: var(--ink-700); }
.sfx-exp-filter.is-active { background: var(--surface-panel); color: var(--ink-900); box-shadow: var(--shadow-xs); }
</style>
