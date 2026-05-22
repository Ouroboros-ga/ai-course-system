<template>
  <div class="chat-page-container">
    <!-- 顶部导航：动画 1 -->
    <ChatTopNav
      class="fade-in-up"
      :show-history="showHistory"
      @toggle-history="showHistory = !showHistory"
      @create-new-session="createNewSession"
    />

    <HistorySidebar :show-history="showHistory">
      <ChatHistory />
    </HistorySidebar>

    <!-- 内容区域：动画 2 -->
    <div class="content-box fade-in-up">
      <DesktopLayout v-if="!isMobile" :show-history="showHistory">
      <template #main>
        <PptPlayer
          :initialData="currentData"
          :reset-trigger="resetTrigger"
          @file-upload="handleFileUpload"
          @analysis-complete="handleAnalysisComplete"
        />
      </template>
      <template #sidebar>
        <ChatPanel 
          :hasFile="!!currentFile" 
          :isAnalyzing="isAnalyzing"
          :hasValidData="hasValidData"
          :currentData="currentData"
        />
      </template>
    </DesktopLayout>

    <MobileLayout v-else :default-tab="activeTab" @tab-change="activeTab = $event">
      <template #ppt>
        <PptPlayer
          :initialData="currentData"
          :reset-trigger="resetTrigger"
          @file-upload="handleFileUpload"
          @analysis-complete="handleAnalysisComplete"
        />
      </template>
      <template #chat>
        <ChatPanel 
          :hasFile="!!currentFile" 
          :isAnalyzing="isAnalyzing"
          :hasValidData="hasValidData"
          :currentData="currentData"
        />
      </template>
    </MobileLayout>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue';
import PptPlayer from '@/components/chat/player/PptPlayer.vue';
import ChatPanel from '@/components/chat/panel/ChatPanel.vue';
import ChatHistory from '@/components/chat/history/ChatHistory.vue';
import ChatTopNav from '@/components/chat/topnav/ChatTopNav.vue';
import HistorySidebar from '@/components/chat/sidebar/HistorySidebar.vue';
import DesktopLayout from '@/components/chat/layout/DesktopLayout.vue';
import MobileLayout from '@/components/chat/layout/MobileLayout.vue';

const STORAGE_KEY = 'chatCurrentData';

const currentFile = ref(null);
const currentData = ref(null);
const isAnalyzing = ref(false);
const showHistory = ref(false);
const activeTab = ref('ppt');
const isMobile = ref(false);
const resetTrigger = ref(0);

const hasValidData = computed(() => {
  return Boolean(currentData.value?.chatId && currentData.value?.content);
});

const loadFromStorage = () => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (parsed && typeof parsed === 'object') {
        if (parsed.currentFile) {
          currentFile.value = parsed.currentFile;
        }
        if (parsed.currentData && parsed.currentData.chatId) {
          currentData.value = parsed.currentData;
        }
      }
    }
  } catch (e) {
    localStorage.removeItem(STORAGE_KEY);
  }
};

const saveToStorage = () => {
  try {
    const dataToSave = {
      currentFile: currentFile.value,
      currentData: currentData.value,
      savedAt: new Date().toISOString()
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(dataToSave));
  } catch (e) {
  }
};

watch([currentFile, currentData], () => {
  saveToStorage();
}, { deep: true });

const handleFileUpload = (file) => {
  currentFile.value = file;
  currentData.value = null;
  isAnalyzing.value = true;
};

const handleAnalysisComplete = (data) => {
  currentData.value = data;
  isAnalyzing.value = false;
};

const createNewSession = () => {
  currentFile.value = null;
  currentData.value = null;
  isAnalyzing.value = false;
  localStorage.removeItem('chatMessages');
  localStorage.removeItem(STORAGE_KEY);
  resetTrigger.value += 1;
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
  loadFromStorage();
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

.content-box {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 16px;
  box-sizing: border-box;
  position: relative;
}

/* ====================== */
/* 🔥 统一高级淡入动画 */
/* ====================== */
.fade-in-up {
  opacity: 0;
  transform: translateY(35px);
  animation: fadeInUp 0.7s cubic-bezier(0.24, 1, 0.32, 1) forwards;
}

/* 依次出现：导航 → 内容 */
.fade-in-up:nth-child(1) { animation-delay: 0.1s; }
.fade-in-up:nth-child(3) { animation-delay: 0.25s; }

@keyframes fadeInUp {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 768px) {
  .chat-page-container {
    height: 100vh;
    overflow: hidden;
  }

  .content-box {
    padding: 0 12px 12px;
  }
}
</style>
