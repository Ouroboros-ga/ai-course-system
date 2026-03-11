<script setup>

</script>

<template>
  <div class="chat-box">
    <h1>这是chatBox组件</h1>
    <h1>这是chatBox组件</h1>
    <h1>这是chatBox组件</h1>
    <h1>这是chatBox组件</h1>
    <h1>这是chatBox组件这是chatBox组件这是chatBox组件这是chatBox组件</h1>
    <h1>这是chatBox组件</h1>
    <h1>这是chatBox组件</h1>
    <h1>这是chatBox组件</h1>
    <h1>这是chatBox组件</h1>
    <h1>这是chatBox组件</h1>
    <h1>这是chatBox组件</h1>
    <h1>这是chatBox组件</h1>
    <h1>这是chatBox组件</h1>
  </div>
</template>

<style scoped>
.chat-box {
  /* 容器尺寸和定位 */
  max-width: 800px;
  margin: 0 auto;
  padding: 20px;
  height: 65vh;
  overflow-y: auto;

  /* 背景和内边距 */
  background: transparent;
  display: flex;
  flex-direction: column;
  gap: 16px;

  /* 滚动条美化 */
  scrollbar-width: thin;
  scrollbar-color: rgba(0, 0, 0, 0.2) transparent;
}

/* Webkit 浏览器滚动条 */
.chat-box::-webkit-scrollbar {
  width: 6px;
}

.chat-box::-webkit-scrollbar-track {
  background: transparent;
}

.chat-box::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 3px;
}

.chat-box::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.3);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .chat-box {
    padding: 12px;
    gap: 12px;
    height: calc(100vh - 160px);
  }
}
</style>

