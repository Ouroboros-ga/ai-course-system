<script setup>
import { computed } from 'vue'
import {
  AlertTriangle, Bot, CircleX, ClipboardCheck, FileClock,
  RefreshCw, TerminalSquare, X
} from 'lucide-vue-next'
import PrototypeStatusBadge from './PrototypeStatusBadge.vue'

const props = defineProps({
  checks: { type: Array, required: true },
  tasks: { type: Array, required: true },
  activeTab: { type: String, required: true },
  mobile: { type: Boolean, default: false },
  activeStep: { type: Object, required: true }
})

const emit = defineEmits(['update:active-tab', 'retry-task', 'open-step', 'close'])

const blockers = computed(() => props.checks.filter((item) => item.severity === 'blocker' && !item.resolved))
const warnings = computed(() => props.checks.filter((item) => item.severity === 'warning' && !item.resolved))
</script>

<template>
  <aside class="fd-rail fd-quality" aria-label="质量检查与任务日志">
    <div class="fd-quality__tabs" role="tablist" aria-label="检查面板">
      <button type="button" role="tab" :aria-selected="activeTab === 'quality'" :class="{ 'is-active': activeTab === 'quality' }" @click="emit('update:active-tab', 'quality')">
        <ClipboardCheck :size="16" />质量检查
      </button>
      <button type="button" role="tab" :aria-selected="activeTab === 'suggestion'" :class="{ 'is-active': activeTab === 'suggestion' }" @click="emit('update:active-tab', 'suggestion')">
        <Bot :size="16" />AI 建议
      </button>
      <button type="button" role="tab" :aria-selected="activeTab === 'log'" :class="{ 'is-active': activeTab === 'log' }" @click="emit('update:active-tab', 'log')">
        <TerminalSquare :size="16" />任务日志
      </button>
      <button v-if="mobile" class="fd-icon-button" type="button" aria-label="关闭检查面板" @click="emit('close')"><X :size="17" /></button>
    </div>

    <div class="fd-quality__scroll">
      <template v-if="activeTab === 'quality'">
        <section class="fd-quality-card">
          <header>
            <h2>当前步骤</h2>
            <PrototypeStatusBadge :status="activeStep.status" compact />
          </header>
          <strong>{{ activeStep.title }}</strong>
          <p>AI 产物需由教师核对后才可进入下一阶段；生成成功不等于确认完成。</p>
        </section>

        <section class="fd-quality-card">
          <header>
            <h2>缺失项</h2>
            <span>{{ blockers.length + warnings.length }}</span>
          </header>
          <button v-for="check in checks" :key="check.id" class="fd-check-item" type="button" @click="emit('open-step', check.step)">
            <component :is="check.severity === 'blocker' ? CircleX : AlertTriangle" :size="16" />
            <span>{{ check.title }}</span>
            <small>{{ check.severity === 'blocker' ? '阻断' : '警告' }}</small>
          </button>
        </section>

        <section class="fd-quality-card">
          <header><h2>发布检查清单</h2><span>78%</span></header>
          <div class="fd-progress-line"><i style="width: 78%"></i></div>
          <div class="fd-check-summary">
            <span><CircleX :size="15" />阻断项 {{ blockers.length }}</span>
            <span><AlertTriangle :size="15" />警告项 {{ warnings.length }}</span>
          </div>
        </section>
      </template>

      <template v-else-if="activeTab === 'suggestion'">
        <section class="fd-quality-card fd-ai-suggestion">
          <header><h2>AI 建议</h2><span class="fd-ai-mark">AI</span></header>
          <p>脚本块 2 的定义准确，但可在“特定关系”后补充线性与非线性结构的对照例子。</p>
          <button class="fd-text-button" type="button">定位到脚本块 2</button>
        </section>
        <section class="fd-quality-card">
          <p class="fd-muted">AI 建议不会自动覆盖教师内容；采纳后仍需人工确认。</p>
        </section>
      </template>

      <template v-else>
        <section v-for="task in tasks" :key="task.id" class="fd-task-card" :class="'is-' + task.status">
          <header>
            <FileClock :size="17" />
            <strong>{{ task.title }}</strong>
            <PrototypeStatusBadge :status="task.status" compact />
          </header>
          <div v-if="task.status === 'running'" class="fd-progress-line"><i :style="{ width: task.progress + '%' }"></i></div>
          <p v-if="task.error">{{ task.error }}</p>
          <small v-else>任务可在离开页面后继续，完成后在任务中心查看。</small>
          <button v-if="task.retryable && task.status === 'failed'" class="fd-secondary-button" type="button" @click="emit('retry-task', task.id)">
            <RefreshCw :size="15" />重试
          </button>
        </section>
      </template>
    </div>
  </aside>
</template>
