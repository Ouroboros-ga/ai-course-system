<script setup>
import { AlertCircle, CheckCircle2, ChevronLeft, Circle, Clock3, LoaderCircle, XCircle, X } from 'lucide-vue-next'
import PrototypeStatusBadge from './PrototypeStatusBadge.vue'

defineProps({
  steps: { type: Array, required: true },
  activeKey: { type: String, required: true },
  mobile: { type: Boolean, default: false }
})

const emit = defineEmits(['select', 'close'])

const statusIcon = (status) => ({
  confirmed: CheckCircle2,
  processing: LoaderCircle,
  review_required: Clock3,
  warning: AlertCircle,
  failed: XCircle
}[status] || Circle)
</script>

<template>
  <aside class="fd-rail fd-pipeline" aria-label="课程制作流程">
    <div class="fd-rail__header">
      <div>
        <p class="fd-eyebrow">从资料到发布</p>
        <h2>课程制作流程</h2>
      </div>
      <button v-if="mobile" class="fd-icon-button" type="button" aria-label="关闭制作流程" @click="emit('close')">
        <X :size="18" />
      </button>
    </div>

    <ol class="fd-pipeline__steps">
      <li v-for="(step, index) in steps" :key="step.key">
        <button
          type="button"
          :class="['fd-pipeline-step', 'is-' + step.status, { 'is-active': activeKey === step.key }]"
          :aria-current="activeKey === step.key ? 'step' : undefined"
          @click="emit('select', step)"
        >
          <span class="fd-pipeline-step__index">
            <component :is="statusIcon(step.status)" :size="17" />
            <small>{{ index + 1 }}</small>
          </span>
          <span class="fd-pipeline-step__copy">
            <strong>{{ step.title }}</strong>
            <small>{{ step.meta }}</small>
          </span>
          <PrototypeStatusBadge :status="step.status" compact />
        </button>
      </li>
    </ol>

    <button class="fd-collapse-action" type="button" @click="emit('close')">
      <ChevronLeft :size="16" />收起流程
    </button>
  </aside>
</template>
