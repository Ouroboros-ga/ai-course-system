<template>
  <header class="top-nav">
    <button class="new-session-btn" @click="createNewSession">
      <span class="icon">+</span>
      <span class="text">新建会话</span>
    </button>
    <button class="history-btn" @click="toggleHistory">
      <span v-if="showHistory">←</span>
      <span v-else>三</span>
    </button>
    <div class="nav-title">Smartrab 课堂</div>
    <button class="upload-btn" @click="handleUpload">
      上传智课
    </button>
  </header>
</template>

<script setup>
defineProps({
  showHistory: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['toggle-history', 'create-new-session', 'open-upload'])

const toggleHistory = () => {
  emit('toggle-history')
}

const createNewSession = () => {
  emit('create-new-session')
}

const handleUpload = () => {
  emit('open-upload')
}
</script>

<style scoped>
.top-nav {
  position: relative;
  height: 48px;
  background: white;
  display: flex;
  align-items: center;
  padding: 0 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  z-index: 9999;
  gap: 8px;
}
.history-btn {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  border: none;
  background: #f1f5f9;
  font-size: 16px;
  font-weight: bold;
  color: #333;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}
.history-btn:hover {
  background: #e2e8f0;
}
.nav-title {
  flex: 1;
  text-align: center;
  font-size: 16px;
  font-weight: 600;
  color: #111;
}
.new-session-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 10px;
  border: none;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 2px 4px rgba(102, 126, 234, 0.3);
}
.new-session-btn:hover {
  background: linear-gradient(135deg, #5a6fd6 0%, #6a4190 100%);
  box-shadow: 0 4px 8px rgba(102, 126, 234, 0.4);
  transform: translateY(-1px);
}
.new-session-btn:active {
  transform: translateY(0);
  box-shadow: 0 1px 2px rgba(102, 126, 234, 0.3);
}
.new-session-btn .icon {
  font-size: 18px;
  font-weight: bold;
  line-height: 1;
}
.new-session-btn .text {
  font-size: 13px;
}

/* 上传按钮 */
.upload-btn {
  padding: 8px 18px;
  border-radius: 10px;
  border: none;
  background: #2563eb;
  color: white;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 2px 4px rgba(37, 99, 235, 0.3);
}
.upload-btn:hover {
  background: #1d4ed8;
  box-shadow: 0 4px 8px rgba(37, 99, 235, 0.4);
  transform: translateY(-1px);
}
.upload-btn:active {
  transform: translateY(0);
  box-shadow: 0 1px 2px rgba(37, 99, 235, 0.3);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .new-session-btn .text {
    display: none;
  }
  .new-session-btn {
    padding: 8px 10px;
  }
  .upload-btn {
    padding: 8px 12px;
    font-size: 13px;
  }
}
</style>
