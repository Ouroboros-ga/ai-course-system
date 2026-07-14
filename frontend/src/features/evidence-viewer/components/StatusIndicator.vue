<template>
  <span
    class="ev-status-indicator"
    :class="[`ev-status--${status}`, sizeClass]"
    :title="tooltip"
    role="status"
    :aria-label="tooltip"
  >
    <span class="ev-status-dot" aria-hidden="true"></span>
    <span class="ev-status-label">{{ label }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** Evidence status: 'active' | 'stale' | 'suspended' | 'missing' | 'approximate' | 'invalid' */
  status: { type: String, default: 'active' },
  /** Size variant: 'sm' | 'md' | 'lg' */
  size: { type: String, default: 'sm' },
})

const sizeClass = computed(() => `ev-status--${props.size}`)

const label = computed(() => {
  const map = {
    active: 'Verified',
    stale: 'Stale',
    suspended: 'Suspended',
    missing: 'No Coordinates',
    approximate: 'Approximate',
    invalid: 'Invalid Data',
  }
  return map[props.status] ?? props.status
})

const tooltip = computed(() => {
  const map = {
    active: 'Evidence is current and verified',
    stale: 'This evidence refers to a superseded document version',
    suspended: 'This evidence has been temporarily excluded',
    missing: 'Coordinate data is not available for this evidence',
    approximate: 'Coordinates are approximate and may not be precise',
    invalid: 'Coordinate data could not be parsed (fail-closed)',
  }
  return map[props.status] ?? ''
})
</script>

<style scoped>
.ev-status-indicator {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 4px;
  font-weight: 500;
  white-space: nowrap;
}

.ev-status-dot {
  display: inline-block;
  border-radius: 50%;
  flex-shrink: 0;
}

.ev-status-label {
  font-size: inherit;
}

/* Sizes */
.ev-status--sm { font-size: 11px; }
.ev-status--sm .ev-status-dot { width: 6px; height: 6px; }
.ev-status--md { font-size: 12px; padding: 2px 6px; }
.ev-status--md .ev-status-dot { width: 8px; height: 8px; }
.ev-status--lg { font-size: 13px; padding: 3px 8px; }
.ev-status--lg .ev-status-dot { width: 10px; height: 10px; }

/* Status colors */
.ev-status--active { color: #16a34a; }
.ev-status--active .ev-status-dot { background: #16a34a; }

.ev-status--stale { color: #ca8a04; }
.ev-status--stale .ev-status-dot { background: #ca8a04; }

.ev-status--suspended { color: #6b7280; }
.ev-status--suspended .ev-status-dot { background: #6b7280; }

.ev-status--missing { color: #9333ea; }
.ev-status--missing .ev-status-dot { background: #9333ea; }

.ev-status--approximate { color: #ea580c; }
.ev-status--approximate .ev-status-dot { background: #ea580c; }

.ev-status--invalid { color: #dc2626; }
.ev-status--invalid .ev-status-dot { background: #dc2626; }
</style>
