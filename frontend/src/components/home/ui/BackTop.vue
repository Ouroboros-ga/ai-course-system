<template>
  <button class="back-top" @click="$emit('go-top')">
    <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="3">
      <path d="M18 15l-6-6-6 6" />
    </svg>
  </button>
</template>
<style scoped>
.back-top { position: fixed; right: 2rem; bottom: 2rem; width: 3rem; height: 3rem; background: white; border: 1px solid #e2e8f0; border-radius: 12px; cursor: pointer; display: flex; align-items: center; justify-content: center; color: #3b82f6; transition: 0.3s; }
.back-top:hover { background: #3b82f6; color: white; transform: scale(1.1); }
</style>
