<script setup>
import { Check, Clock, CircleAlert, Info, X } from 'lucide-vue-next'
import { computed } from 'vue'

/**
 * 状态徽标：图标 + 文字 + 颜色，三者缺一不可（design.md 4.7）。
 * 不允许只用颜色点表达关键状态。
 */
const props = defineProps({
  tone: {
    type: String,
    default: 'neutral',
    validator: (v) => ['green', 'amber', 'red', 'ink', 'neutral'].includes(v),
  },
})

const iconMap = {
  green: Check,
  amber: Clock,
  red: X,
  ink: Info,
  neutral: CircleAlert,
}

const iconComponent = computed(() => iconMap[props.tone] ?? Info)
</script>

<template>
  <span class="sfx-badge" :class="`is-${tone}`">
    <component :is="iconComponent" :size="13" :stroke-width="2.4" aria-hidden="true" />
    <span class="sfx-badge-text"><slot /></span>
  </span>
</template>

<style scoped>
.sfx-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 24px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--caption-size);
  font-weight: 500;
  white-space: nowrap;
}

.sfx-badge.is-green { background: var(--green-100); color: var(--green-700); }
.sfx-badge.is-amber { background: var(--amber-100); color: var(--amber-700); }
.sfx-badge.is-red { background: var(--red-100); color: var(--red-700); }
.sfx-badge.is-ink { background: var(--ink-100); color: var(--ink-700); }
.sfx-badge.is-neutral { background: var(--surface-cool); color: var(--text-secondary); }
</style>
