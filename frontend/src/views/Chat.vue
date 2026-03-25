<template>
  <div class="chat-page-container">
    <!-- 历史记录侧边栏 -->
    <div class="history-sidebar" :class="{ open: showHistory }">
      <ChatHistory v-if="showHistory" />

      <button class="toggle-btn" @click="showHistory = !showHistory">
        <span v-if="showHistory">←</span>
        <span v-else>三</span>
      </button>

      <div class="mobile-profile" v-if="showHistory">
        <img src="https://picsum.photos/200/200" alt="profile" />
      </div>
    </div>

    <!-- 内容区域 -->
    <div class="content-box">
      <!-- 桌面端三栏布局 -->
      <div v-if="!isMobile" class="desktop-layout">
        <div class="main-content">
          <PptPlayer
            @file-upload="handleFileUpload"
            @analysis-end="isAnalyzing = false"
          />
        </div>

        <div class="chat-sidebar" v-show="!showHistory">
          <ChatPanel :hasFile="!!currentFile" />
        </div>
      </div>

      <!-- 移动端全屏切换布局 -->
      <div v-else class="mobile-layout">
        <div v-show="activeTab === 'ppt'">
          <PptPlayer
            @file-upload="handleFileUpload"
            @analysis-end="isAnalyzing = false"
          />
        </div>

        <div v-show="activeTab === 'chat'">
          <ChatPanel :hasFile="!!currentFile" />
        </div>

        <!-- 底部TAB -->
        <div class="mobile-tab">
          <button @click="activeTab = 'ppt'" :class="{ active: activeTab === 'ppt' }">
            PPT
          </button>
          <button @click="activeTab = 'chat'" :class="{ active: activeTab === 'chat' }">
            对话
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
import PptPlayer from '@/components/chat/PptPlayer.vue';
import ChatPanel from '@/components/chat/ChatPanel.vue';
import ChatHistory from '@/components/chat/ChatHistory.vue';

const currentFile = ref(null);
const isAnalyzing = ref(false);
const showHistory = ref(false);
const activeTab = ref('ppt');
const isMobile = ref(false);

const handleFileUpload = (file) => {
  currentFile.value = file;
  isAnalyzing.value = true;
};

const checkMobile = () => {
  const newIsMobile = window.innerWidth <= 768;

  // 👇👇👇 关键逻辑：只要屏幕切换，就关闭历史
  if (newIsMobile !== isMobile.value) {
    showHistory.value = false;
  }

  isMobile.value = newIsMobile;
};

onMounted(() => {
  checkMobile();
  window.addEventListener('resize', checkMobile);
});

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile);
});
</script>

<style scoped>
.chat-page-container {
  display: flex;
  gap: 16px;
  padding: 16px;
  width: 100%;
  height: 900px !important;
  background: #f8fafc;
  position: relative;
  font-family: system-ui, sans-serif;
}

.content-box {
  flex: 1;
  display: flex;
  flex-direction: column;
}

/* -------------------------- */
/* 历史侧边栏 - 桌面端正常
/* -------------------------- */
.history-sidebar {
  width: 52px;
  flex-shrink: 0;
  background: white;
  border-radius: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  transition: width 0.3s ease;
  overflow: hidden;
  position: relative;
}
.history-sidebar.open {
  width: 240px;
}

.toggle-btn {
  position: absolute;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
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
  z-index: 10;
}

/* -------------------------- */
/* 桌面布局
/* -------------------------- */
.desktop-layout {
  display: flex;
  gap: 16px;
  flex: 1;
}

.main-content {
  flex: 1;
  background: white;
  border-radius: 16px;
  overflow: hidden;
}
.chat-sidebar {
  width: 380px;
  flex-shrink: 0;
  background: white;
  border-radius: 16px;
  overflow: hidden;
}

/* -------------------------- */
/* 移动端布局
/* -------------------------- */
@media (max-width: 768px) {
  .chat-page-container {
    flex-direction: column;
    height: auto !important;
    min-height: 100vh !important;
    padding: 12px;
    padding-bottom: 70px;
  }

  .mobile-layout {
    display: flex;
    flex-direction: column;
    flex: 1;
  }

  /* 底部TAB */
  .mobile-tab {
    position: fixed;
    bottom: 0;
    left: 0;
    width: 100%;
    height: 60px;
    background: white;
    display: flex;
    box-shadow: 0 -2px 10px rgba(0,0,0,0.1);
    z-index: 100;
  }
  .mobile-tab button {
    flex: 1;
    border: none;
    background: none;
    font-size: 15px;
    color: #666;
  }
  .mobile-tab button.active {
    color: #4f46e5;
    font-weight: bold;
  }

  /* 历史悬浮球 */
  .history-sidebar {
    position: fixed;
    top: 20px;
    left: 20px;
    width: 48px !important;
    height: 48px !important;
    border-radius: 14px;
  }
  .history-sidebar.open {
    width: 85vw !important;
    height: 80vh !important;
    border-radius: 24px;
    padding: 60px 20px 20px 20px;
  }
}

.mobile-profile {
  display: none;
  position: absolute;
  bottom: 20px;
  left: 20px;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  overflow: hidden;
}
</style>
