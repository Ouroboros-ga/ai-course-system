<script setup>
import { FlaskConical, Microscope } from 'lucide-vue-next'
import { computed } from 'vue'

/**
 * 能力成熟度标签（page-design §6.11 / §22.8）。
 * 必须用于：实验能力、研究预览、Shadow/Dry-run、试验性能力。
 * 不允许把实验/研究能力伪装成正式产品能力。
 */
const props = defineProps({
  level: {
    type: String,
    default: 'experimental',
    validator: (v) => ['experimental', 'research'].includes(v),
  },
})

const meta = computed(() =>
  props.level === 'research'
    ? { label: '研究预览', icon: Microscope, cls: 'is-research' }
    : { label: '实验能力', icon: FlaskConical, cls: 'is-experimental' }
)
</script>

<template>
  <span class="sfx-cap" :class="meta.cls" :title="`该能力为${meta.label}，可能不稳定或受限`">
    <component :is="meta.icon" :size="12" :stroke-width="2.2" aria-hidden="true" />
    <span>{{ meta.label }}</span>
  </span>
</template>

<style scoped>
.sfx-cap {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 22px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--caption-size);
  font-weight: 500;
  white-space: nowrap;
  border: 1px dashed currentColor;
}

.sfx-cap.is-experimental {
  color: var(--ink-500);
  background: var(--surface-cool);
}

.sfx-cap.is-research {
  color: var(--amber-700);
  background: var(--amber-100);
}
</style>
