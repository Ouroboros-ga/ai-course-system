<template>
  <div class="knowledge-view">
    <KnowledgeProgressPage />
  </div>
</template>

<script setup>
import KnowledgeProgressPage from '@/components/chat/player/PptPlayer/KnowledgeProgressPage.vue'
</script>

<style scoped>
.knowledge-view {
  min-height: calc(100vh - var(--navbar-height));
  background: #f5f7fa;
}
</style>
