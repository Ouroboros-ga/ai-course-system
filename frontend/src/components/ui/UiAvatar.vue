<script setup>
import { computed } from 'vue'

const props = defineProps({
  src: {
    type: String,
    default: '',
  },
  name: {
    type: String,
    default: '',
  },
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg'].includes(v),
  },
  variant: {
    type: String,
    default: 'primary',
    validator: (v) => ['primary', 'neutral'].includes(v),
  },
})

const dimension = computed(() => {
  const map = { sm: '32px', md: '40px', lg: '56px' }
  return map[props.size]
})

const fontSize = computed(() => {
  const map = { sm: 'var(--text-sm)', md: 'var(--text-base)', lg: 'var(--text-xl)' }
  return map[props.size]
})

const initial = computed(() => {
  if (!props.name) return ''
  return props.name.charAt(0).toUpperCase()
})
</script>

<template>
  <div
    class="ui-avatar"
    :class="[`ui-avatar--${variant}`]"
    :style="{ width: dimension, height: dimension, fontSize }"
    role="img"
    :aria-label="name || '头像'"
  >
    <img v-if="src" :src="src" :alt="name || '头像'" class="ui-avatar__img" />
    <span v-else class="ui-avatar__initial">{{ initial }}</span>
  </div>
</template>

<style scoped>
.ui-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  overflow: hidden;
  font-family: var(--font-sans);
  font-weight: var(--font-semibold);
  line-height: 1;
  flex-shrink: 0;
}

.ui-avatar--primary {
  background: var(--gradient-primary);
  color: var(--color-primary-foreground);
}

.ui-avatar--neutral {
  background: var(--color-surface-2);
  color: var(--color-text-secondary);
}

.ui-avatar__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.ui-avatar__initial {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-transform: uppercase;
}
</style>
