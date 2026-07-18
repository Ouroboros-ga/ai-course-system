<script setup>
import { computed } from 'vue'
import { prototypeStatusLabels } from '../mock/frontendDesignMocks.js'

const props = defineProps({
  status: { type: String, default: 'not_started' },
  label: { type: String, default: '' },
  compact: { type: Boolean, default: false }
})

const text = computed(() => props.label || prototypeStatusLabels[props.status] || props.status)
</script>

<template>
  <span class="fd-status" :class="['fd-status--' + status, { 'fd-status--compact': compact }]">
    <span class="fd-status__dot" aria-hidden="true"></span>
    <span>{{ text }}</span>
  </span>
</template>
