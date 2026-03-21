<template>
  <div class="ppt-section">
    <!-- 头部 -->
    <PptHeader :file="file" :totalPages="45" />

    <!-- 内容区 -->
    <div class="ppt-display-area">
      <PptUpload v-if="!file" @click="triggerUpload" @drop="handleDrop" />
      <PptAnalyzing v-else-if="isAnalyzing" />

      <div v-else class="ppt-content-wrapper">
        <div class="ppt-placeholder">
          <div style="font-size: 48px; color: #fee2e2; margin-bottom: 16px;">📊</div>
          <p>PPT 第 12 页预览区域</p>
          <span style="font-size: 12px; color: #9ca3af;">(此处接入 PDF/PPT 渲染组件)</span>
        </div>
        <PptControlBar :isPlaying="isPlaying" @toggle="togglePlay" />
      </div>

      <input type="file" ref="fileInput" @change="handleFileChange" class="hidden-input" accept=".ppt,.pptx,.pdf">
    </div>
  </div>
</template>

<script setup>
import { ref, defineEmits } from 'vue';
import PptHeader from './PptPlayer/PptHeader.vue';
import PptUpload from './PptPlayer/PptUpload.vue';
import PptAnalyzing from './PptPlayer/PptAnalyzing.vue';
import PptControlBar from './PptPlayer/PptControlBar.vue';

const emit = defineEmits(['file-upload', 'analysis-end']);
const file = ref(null);
const isAnalyzing = ref(false);
const isPlaying = ref(false);
const fileInput = ref(null);

const triggerUpload = () => fileInput.value.click();
const handleFileChange = (e) => startAnalysis(e.target.files[0]);
const handleDrop = (e) => startAnalysis(e.dataTransfer.files[0]);

const startAnalysis = (f) => {
  if(!f) return;
  file.value = f;
  emit('file-upload', f);
  isAnalyzing.value = true;
  setTimeout(() => { isAnalyzing.value = false; isPlaying.value = true; emit('analysis-end'); }, 3000);
};
const togglePlay = () => isPlaying.value = !isPlaying.value;
</script>

<style scoped>
.ppt-section {
  flex: 6.5; /* 左侧占 6.5 份 */
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
  height: 100%;
}

.ppt-display-area {
  flex: 1;
  background: white;
  border-radius: 16px;
  box-shadow: 0 10px 25px -5px rgba(0,0,0,0.1);
  border: 1px solid #f3f4f6;
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 500px;
}

.ppt-content-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.ppt-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: #9ca3af;
}

.hidden-input {
  display: none;
}

/* 📱 移动端适配 */
@media (max-width: 768px) {
  .ppt-section {
    flex: none;
    width: 100%;
    height: 45vh;
    min-height: 300px;
  }
  .ppt-display-area {
    min-height: auto;
  }
}
</style>
