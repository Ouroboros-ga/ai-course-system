<template>
  <div class="knowledge-view">
    <NavigationBar />
    <KnowledgeProgressPage />
  </div>
</template>

<script setup>
import NavigationBar from '@/components/NavigationBar.vue'
import KnowledgeProgressPage from '@/components/chat/player/PptPlayer/KnowledgeProgressPage.vue'
</script>

<style scoped>
.knowledge-view {
  min-height: 100vh;
  background: #f5f7fa;
}
</style>
