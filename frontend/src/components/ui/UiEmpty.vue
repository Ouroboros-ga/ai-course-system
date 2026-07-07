<script setup>
import { computed } from 'vue'
import * as icons from 'lucide-vue-next'

const props = defineProps({
  icon: {
    type: String,
    default: 'Inbox',
  },
  title: {
    type: String,
    default: '暂无数据',
  },
  description: {
    type: String,
    default: '',
  },
})

const iconComponent = computed(() => {
  return icons[props.icon] || icons.Inbox
})
</script>

<template>
  <div class="ui-empty">
    <div class="ui-empty__icon">
      <slot name="icon">
        <component :is="iconComponent" :size="64" :stroke-width="1.5" />
      </slot>
    </div>
    <h3 class="ui-empty__title">{{ title }}</h3>
    <p v-if="description" class="ui-empty__desc">{{ description }}</p>
    <div v-if="$slots.default" class="ui-empty__action">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.ui-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-8) var(--space-5);
  font-family: var(--font-sans);
}

.ui-empty__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  margin-bottom: var(--space-4);
  color: var(--color-text-muted);
}

.ui-empty__title {
  margin: 0 0 var(--space-2);
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--color-text);
  line-height: var(--leading-tight);
}

.ui-empty__desc {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  text-align: center;
  max-width: 300px;
  line-height: var(--leading-relaxed);
}

.ui-empty__action {
  margin-top: var(--space-5);
}
</style>
