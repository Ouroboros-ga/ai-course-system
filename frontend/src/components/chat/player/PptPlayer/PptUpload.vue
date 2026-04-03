<template>
  <div class="upload-container">
    <!-- 我改了 @drop：不直接emit，而是先打开配置 -->
    <div
      class="upload-box"
      @dragover.prevent
      @drop="handleDropWithConfig"
    >
      <div class="upload-icon">📁</div>
      <h3>点击或拖拽上传课件</h3>
      <p>支持 .ppt, .pptx, .pdf 格式</p>
      <button class="btn-upload-primary" @click="$emit('open-config')">
        选择文件
      </button>
    </div>
    <div class="features-hint">
      <span>✨ AI 自动解析知识点</span>
      <span>✨ 生成结构化讲义</span>
      <span>✨ 实时语音互动</span>
    </div>
  </div>
</template>

<script setup>
const emit = defineEmits(['click', 'drop', 'open-config', 'drop-with-config']);

// 拖拽：先存文件 → 打开配置 → 配置确认后再真正上传
const handleDropWithConfig = (e) => {
  e.preventDefault();
  const file = e.dataTransfer.files?.[0];
  if (file) {
    // 把文件传给父组件暂存，并打开配置弹窗
    emit('drop-with-config', file);
  }
};
</script>

<style scoped>
/* 原有样式完全不变 */
.upload-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 20px;
  width: 100%;
}
.upload-box {
  width: 80%;
  max-width: 500px;
  border: 2px dashed #cbd5e1;
  border-radius: 16px;
  padding: 40px;
  text-align: center;
  background: #f8fafc;
  transition: all 0.3s;
  cursor: pointer;
}
.upload-box:hover {
  border-color: #3b82f6;
  background: #eff6ff;
}
.upload-icon {
  font-size: 48px;
  margin-bottom: 16px;
}
.upload-box h3 {
  margin: 0 0 8px 0;
  color: #334155;
}
.upload-box p {
  margin: 0 0 24px 0;
  color: #64748b;
  font-size: 14px;
}
.btn-upload-primary {
  background: #2563eb;
  color: white;
  border: none;
  padding: 10px 24px;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
}
.features-hint {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: #64748b;
}
</style>
