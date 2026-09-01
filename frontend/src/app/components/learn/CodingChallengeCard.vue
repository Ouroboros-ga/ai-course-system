<script setup>
import { Braces, CircleCheck, Clock3, RefreshCw, TriangleAlert } from 'lucide-vue-next'

import SfxButton from '@/app/ui/SfxButton.vue'

defineProps({
  offer: { type: Object, required: true },
  busy: { type: Boolean, default: false },
})

defineEmits(['start', 'dismiss', 'replace'])

const statusCopy = {
  preparing: '正在准备',
  ready: '可以开始',
  failed: '准备失败',
  dismissed: '已稍后处理',
  expired: '已过期',
  started: '练习进行中',
  closed: '本次练习已结束',
}
</script>

<template>
  <section class="coding-offer" :class="`is-${offer.status}`" aria-label="代码挑战建议">
    <header class="coding-offer-head">
      <span class="coding-offer-icon" aria-hidden="true"><Braces :size="18" /></span>
      <div>
        <p class="coding-offer-kicker">代码挑战</p>
        <h3>{{ offer.title || '正在准备一道练习' }}</h3>
      </div>
      <span class="coding-offer-status" role="status">
        <Clock3 v-if="offer.status === 'preparing'" :size="13" />
        <CircleCheck v-else-if="offer.status === 'ready' || offer.status === 'started'" :size="13" />
        <TriangleAlert v-else :size="13" />
        {{ statusCopy[offer.status] || offer.status }}
      </span>
    </header>

    <p v-if="offer.why_now" class="coding-offer-why">
      <strong>为什么现在：</strong>{{ offer.why_now }}
    </p>
    <p class="coding-offer-meta">
      {{ offer.difficulty || '适中' }}
      <template v-if="offer.estimated_minutes"> · 约 {{ offer.estimated_minutes }} 分钟</template>
      <template v-if="offer.source"> · {{ offer.source === 'ai' ? '智能生成并经沙箱验证' : '课程已验证题' }}</template>
    </p>

    <p v-if="offer.status === 'preparing'" class="coding-offer-note">
      教学回答已完成，题目会在校验通过后原地出现。
    </p>
    <p v-else-if="offer.status === 'failed'" class="coding-offer-note is-error">
      这道题没有通过质量校验，不会作为学习证据。
    </p>

    <div v-if="offer.actions" class="coding-offer-actions">
      <SfxButton
        v-if="offer.actions.can_start"
        variant="primary"
        size="sm"
        :loading="busy"
        @click="$emit('start', offer)"
      >进入代码空间</SfxButton>
      <SfxButton
        v-if="offer.actions.can_replace"
        variant="secondary"
        size="sm"
        :disabled="busy"
        @click="$emit('replace', offer)"
      >
        <template #icon><RefreshCw :size="14" /></template>
        换一道
      </SfxButton>
      <SfxButton
        v-if="offer.actions.can_dismiss"
        variant="tertiary"
        size="sm"
        :disabled="busy"
        @click="$emit('dismiss', offer)"
      >稍后再说</SfxButton>
    </div>
  </section>
</template>

<style scoped>
.coding-offer {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--surface-cool);
}

.coding-offer.is-ready,
.coding-offer.is-started { border-color: var(--ink-300); }
.coding-offer.is-failed { border-color: var(--amber-300); background: var(--amber-100); }

.coding-offer-head { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: start; gap: var(--space-3); }
.coding-offer-icon { width: 34px; height: 34px; display: inline-flex; align-items: center; justify-content: center; border-radius: var(--radius-md); background: var(--ink-100); color: var(--ink-700); }
.coding-offer-kicker { margin: 0 0 var(--space-1); color: var(--text-muted); font-size: var(--caption-size); font-weight: 600; }
.coding-offer h3 { margin: 0; color: var(--ink-900); font-size: var(--title-3-size); line-height: var(--title-3-line); }
.coding-offer-status { display: inline-flex; align-items: center; gap: var(--space-1); min-height: 24px; padding: 2px var(--space-2); border-radius: var(--radius-sm); background: var(--surface-panel); color: var(--text-secondary); font-size: var(--caption-size); white-space: nowrap; }
.coding-offer-why { margin: 0; color: var(--text-primary); font-size: var(--ui-md-size); line-height: 1.7; }
.coding-offer-meta,
.coding-offer-note { margin: 0; color: var(--text-secondary); font-size: var(--caption-size); }
.coding-offer-note.is-error { color: var(--amber-700); }
.coding-offer-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }

@media (max-width: 760px) {
  .coding-offer-head { grid-template-columns: auto minmax(0, 1fr); }
  .coding-offer-status { grid-column: 2; justify-self: start; }
}
</style>
