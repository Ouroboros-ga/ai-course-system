<template>
  <div class="loading-spinner" :class="{ 'full-page': fullPage }">
    <div class="spinner"></div>
    <span v-if="text" class="loading-text">{{ text }}</span>
  </div>
</template>

<script setup>
defineProps({
  text: {
    type: String,
    default: '',
  },
  fullPage: {
    type: Boolean,
    default: false,
  },
})
</script>

<style scoped>
.loading-spinner {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: var(--color-text-muted);
  font-size: 16px;
}

.loading-spinner.full-page {
  min-height: calc(100vh - var(--navbar-height, 60px));
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.loading-text {
  color: var(--color-text-muted);
  font-size: 14px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
