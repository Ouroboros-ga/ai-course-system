<template>
  <div class="upload-container">
    <div class="upload-box" @dragover.prevent @drop="$emit('drop', $event)">
      <div class="upload-icon">📁</div>
      <h3>点击或拖拽上传课件</h3>
      <p>支持 .ppt, .pptx, .pdf 格式</p>
      <button class="btn-upload-primary" @click="$emit('click')">选择文件</button>
    </div>
    <div class="features-hint">
      <span>✨ AI 自动解析知识点</span>
      <span>✨ 生成结构化讲义</span>
      <span>✨ 实时语音互动</span>
    </div>
  </div>
</template>
<script setup>
defineEmits(['click', 'drop']);
</script>
<style scoped>
.upload-container { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; gap: 20px; width: 100%; }
.upload-box { width: 80%; max-width: 500px; border: 2px dashed #cbd5e1; border-radius: 16px; padding: 40px; text-align: center; background: #f8fafc; transition: all 0.3s; cursor: pointer; }
.upload-box:hover { border-color: #3b82f6; background: #eff6ff; }
.upload-icon { font-size: 48px; margin-bottom: 16px; }
.upload-box h3 { margin: 0 0 8px 0; color: #334155; }
.upload-box p { margin: 0 0 24px 0; color: #64748b; font-size: 14px; }
.btn-upload-primary { background: #2563eb; color: white; border: none; padding: 10px 24px; border-radius: 8px; font-weight: 600; cursor: pointer; }
.features-hint { display: flex; gap: 16px; font-size: 13px; color: #64748b; }
</style>
