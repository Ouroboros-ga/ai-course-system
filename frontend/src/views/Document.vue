<template>
  <div class="document-page">
    <DocumentContent />
  </div>
</template>

<script setup>
import DocumentContent from '../components/document/DocumentContent.vue'
</script>

<style scoped>
.document-page {
  height: 75vh;
  display: flex;
  flex-direction: column;
  background-color: rgba(0, 0, 0, 0);
  padding-bottom: env(safe-area-inset-bottom, 80);
}
</style>
