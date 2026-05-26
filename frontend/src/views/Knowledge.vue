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
  min-height: calc(100vh - 56px);
  background: #f5f7fa;
}
</style>
