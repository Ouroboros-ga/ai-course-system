<template>
  <div class="chat-page-container">
    <!-- 顶部导航栏（确保箭头永远可见） -->
    <header class="top-nav">
      <button class="history-btn" @click="showHistory = !showHistory">
        <span v-if="showHistory">←</span>
        <span v-else>三</span>
      </button>
      <div class="nav-title">Smartrab 课堂</div>
    </header>

    <!-- 历史记录侧边栏：修复标题遮挡 -->
    <div class="history-sidebar-wrapper" :class="{ open: showHistory }">
      <div class="history-sidebar">
        <div class="history-header">
          <h3>历史对话</h3>
        </div>
        <ChatHistory />
        <div class="mobile-profile" v-if="showHistory">
          <img src="https://picsum.photos/200/200" alt="profile" />
        </div>
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
        <div class="chat-sidebar" :class="{ hidden: showHistory }">
          <ChatPanel :hasFile="!!currentFile" />
        </div>
      </div>

      <!-- 移动端全屏切换布局 -->
      <div v-else class="mobile-layout">
        <div v-show="activeTab === 'ppt'" class="tab-content">
          <PptPlayer
            @file-upload="handleFileUpload"
            @analysis-end="isAnalyzing = false"
          />
        </div>
        <div v-show="activeTab === 'chat'" class="tab-content">
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
  if (newIsMobile !== isMobile.value) {
    showHistory.value = false;
  }
  isMobile.value = newIsMobile;
};

const preventScroll = (e) => {
  e.preventDefault();
};

onMounted(() => {
  checkMobile();
  window.addEventListener('resize', checkMobile);
  if (isMobile.value) {
    document.body.style.overflow = 'hidden';
    document.addEventListener('touchmove', preventScroll, { passive: false });
  }
});

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile);
  document.body.style.overflow = '';
  document.removeEventListener('touchmove', preventScroll);
});
</script>

<style scoped>
.chat-page-container {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 0;
  width: 100%;
  min-height: 100vh;
  background: #f8fafc;
  position: relative;
  font-family: system-ui, sans-serif;
}

/* 顶部导航栏（所有设备通用） */
.top-nav {
  position: relative;
  height: 48px;
  background: white;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  z-index: 9999;
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
  position: relative;
  z-index: 10000;
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

.content-box {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 16px;
  box-sizing: border-box;
  position: relative;
}

/* -------------------------- */
/* 历史面板：修复标题遮挡 + 不超出背景 */
/* -------------------------- */
.history-sidebar-wrapper {
  position: absolute;
  top: 0;
  left: 0;
  width: 0;
  height: 0;
  border-radius: 16px;
  overflow: hidden;
  z-index: 21;
  transition: all 0.5s cubic-bezier(0.25, 0.8, 0.25, 1);
  transform-origin: top left;
  background: white;
}

.history-sidebar-wrapper.open {
  width: 100%;
  height: 100%;
  border-radius: 16px;
  top: 0;
  left: 0;
}

.history-sidebar {
  width: 100%;
  height: 100%;
  padding: 0; /* 🔴 去掉全局padding，改为给标题单独加padding */
  overflow-y: auto;
  opacity: 0;
  transition: opacity 0.3s ease;
  background: white;
  box-sizing: border-box;
}

.history-sidebar-wrapper.open .history-sidebar {
  opacity: 1;
}

/* 🔴 新增：历史对话标题区域，确保文字不被遮挡 */
.history-header {
  padding: 20px 20px 12px;
  border-bottom: 1px solid #f1f5f9;
}
.history-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #111;
}

/* -------------------------- */
/* 桌面端弹性自适应布局 */
/* -------------------------- */
.desktop-layout {
  display: flex;
  gap: 16px;
  flex: 1;
  position: relative;
  width: 100%;
  box-sizing: border-box;
}

.main-content {
  flex: 2;
  min-width: 300px;
  background: white;
  border-radius: 16px;
  overflow: hidden;
  box-sizing: border-box;
}

.chat-sidebar {
  flex: 1;
  min-width: 280px;
  max-width: 450px;
  background: white;
  border-radius: 16px;
  overflow: hidden;
  transition: all 0.5s cubic-bezier(0.25, 0.8, 0.25, 1);
  opacity: 1;
  transform: translateX(0);
  box-sizing: border-box;
}

.chat-sidebar.hidden {
  opacity: 0;
  transform: translateX(50px);
  pointer-events: none;
}

/* -------------------------- */
/* 移动端：保留动画 + 不超出背景 + 标题可见 */
/* -------------------------- */
@media (max-width: 768px) {
  .chat-page-container {
    height: 100vh;
    overflow: hidden;
  }

  .content-box {
    padding: 0 12px 12px;
  }

  .mobile-layout {
    display: flex;
    flex-direction: column;
    flex: 1;
    height: calc(100vh - 48px - 60px);
  }

  .tab-content {
    flex: 1;
    overflow-y: auto;
    width: 100%;
    box-sizing: border-box;
    background: white;
    border-radius: 16px;
    padding: 12px;
    margin: 0;
  }

  .mobile-tab {
    position: fixed;
    bottom: 0;
    left: 0;
    width: 100%;
    height: 60px;
    background: white;
    display: flex;
    box-shadow: 0 -2px 10px rgba(0,0,0,0.1);
    z-index: 20;
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

  .history-sidebar-wrapper {
    position: absolute !important;
    top: 0 !important;
    left: 0 !important;
    width: 0 !important;
    height: 0 !important;
    border-radius: 16px !important;
    transition: all 0.5s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
    background: white !important;
    z-index: 21 !important;
  }
  .history-sidebar-wrapper.open {
    width: 100% !important;
    height: 100% !important;
    border-radius: 16px !important;
    top: 0 !important;
    left: 0 !important;
    padding: 0 !important;
    max-width: none !important;
  }
  .history-sidebar {
    opacity: 1 !important;
    padding: 0 !important;
  }
  .history-header {
    padding: 20px 20px 12px !important;
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
