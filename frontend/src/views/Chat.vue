<template>
  <div class="chat-page-container">
    <PptPlayer
      @file-upload="handleFileUpload"
      @analysis-end="isAnalyzing = false"
    />
    <ChatPanel :hasFile="!!currentFile" />
  </div>
</template>

<script setup>
import { ref } from 'vue';
import PptPlayer from '@/components/chat/PptPlayer.vue';
import ChatPanel from '@/components/chat/ChatPanel.vue';

const currentFile = ref(null);
const isAnalyzing = ref(false);

const handleFileUpload = (file) => {
  currentFile.value = file;
  isAnalyzing.value = true;
};
</script>

<style scoped>
.chat-page-container {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  padding: 16px;
  align-items: stretch;

  /* 👇 这里改整个页面的高度！想多高就多高！*/
  height: 900px !important;
  min-height: 900px !important;
  max-height: 900px !important;

  width: 100%;
  box-sizing: border-box;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  overflow: hidden;
}

@media (max-width: 768px) {
  .chat-page-container {
    padding: 8px;
    gap: 8px;
    height: auto !important;
    min-height: 100vh !important;
  }
}
</style>
