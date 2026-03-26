<template>
  <div class="chat-page-container">
    <ChatTopNav :show-history="showHistory" @toggle-history="showHistory = !showHistory" />

    <HistorySidebar :show-history="showHistory">
      <ChatHistory />
    </HistorySidebar>

    <div class="content-box">
      <DesktopLayout v-if="!isMobile" :show-history="showHistory">
        <template #main>
          <PptPlayer
            @file-upload="handleFileUpload"
            @analysis-end="isAnalyzing = false"
          />
        </template>
        <template #sidebar>
          <ChatPanel :hasFile="!!currentFile" />
        </template>
      </DesktopLayout>

      <MobileLayout v-else :default-tab="activeTab" @tab-change="activeTab = $event">
        <template #ppt>
          <PptPlayer
            @file-upload="handleFileUpload"
            @analysis-end="isAnalyzing = false"
          />
        </template>
        <template #chat>
          <ChatPanel :hasFile="!!currentFile" />
        </template>
      </MobileLayout>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
import PptPlayer from '@/components/chat/PptPlayer.vue';
import ChatPanel from '@/components/chat/ChatPanel.vue';
import ChatHistory from '@/components/chat/ChatHistory.vue';
import ChatTopNav from '@/components/chat/ChatTopNav.vue';
import HistorySidebar from '@/components/chat/HistorySidebar.vue';
import DesktopLayout from '@/components/chat/DesktopLayout.vue';
import MobileLayout from '@/components/chat/MobileLayout.vue';

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

.content-box {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 16px;
  box-sizing: border-box;
  position: relative;
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
