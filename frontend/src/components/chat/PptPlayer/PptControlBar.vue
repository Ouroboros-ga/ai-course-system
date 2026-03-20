<template>
  <div class="ai-control-bar">
    <!-- 左侧：循环 + 倍速 + 音量 -->
    <div class="control-left">
      <button class="btn-icon" @click="emit('loop')">↺</button>

      <div class="speed-wrapper">
        <button class="speed-tag" @click="toggleSpeedMenu">
          {{ speed }}x
        </button>
        <div class="speed-menu" v-if="showSpeedMenu">
          <button
            v-for="s in [0.5, 1.0, 1.25, 1.5, 2.0]"
            :key="s"
            @click="changeSpeed(s)"
            :class="{ active: s === speed }"
          >
            {{ s }}x
          </button>
        </div>
      </div>

      <button class="btn-icon" @click="toggleMute">
        {{ isMuted ? '🔇' : '🔊' }}
      </button>
    </div>

    <!-- 右侧：播放按钮 + 超长进度条 -->
    <div class="control-right">
      <button class="btn-play" @click="$emit('toggle')">
        <span v-if="isPlaying">⏸</span>
        <span v-else>▶</span>
      </button>

      <div class="progress-container">
        <span class="status-text">{{ isPlaying ? 'AI 讲师正在讲解...' : '已暂停' }}</span>
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: progress + '%' }"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
const props = defineProps(['isPlaying', 'progress']);
const emit = defineEmits(['toggle', 'loop', 'speed-change', 'volume-change']);

const speed = ref(1.0);
const isMuted = ref(false);
const showSpeedMenu = ref(false);

const toggleSpeedMenu = () => {
  showSpeedMenu.value = !showSpeedMenu.value;
};
const changeSpeed = (s) => {
  speed.value = s;
  emit('speed-change', s);
  showSpeedMenu.value = false;
};
const toggleMute = () => {
  isMuted.value = !isMuted.value;
  emit('volume-change', isMuted.value ? 0 : 1);
};
</script>

<style scoped>
/* 你原版的毛玻璃样式 100% 保留 */
.ai-control-bar {
  position: absolute;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  width: 90%;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(8px);
  border-radius: 16px;
  padding: 12px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: 0 10px 25px -5px rgba(37, 99, 235, 0.2);
  border: 1px solid rgba(255,255,255,0.5);
}

.control-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.control-right {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 24px; /* 👈 增大 gap，让按钮和进度条整体右移 */
  margin-left: 16px; /* 👈 给进度条更多空间，不超出容器 */
}

.btn-icon {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 16px;
  color: #6b7280;
}

.speed-wrapper {
  position: relative;
}
.speed-tag {
  font-size: 12px;
  font-family: monospace;
  background: #f3f4f6;
  padding: 2px 6px;
  border-radius: 4px;
  border: none;
  cursor: pointer;
  color: #374151;
}

.speed-menu {
  position: absolute;
  bottom: 30px;
  left: 0;
  background: white;
  border-radius: 8px;
  padding: 6px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  display: flex;
  flex-direction: column;
  gap: 4px;
  z-index: 10;
}
.speed-menu button {
  background: none;
  border: none;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}
.speed-menu button.active {
  background: #dbeafe;
  color: #2563eb;
}

.btn-play {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #2563eb;
  color: white;
  border: none;
  font-size: 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-left: 8px; /* 👈 让按钮本身再往右挪一点 */
}

.progress-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.status-text {
  font-size: 12px;
  color: #6b7280;
  font-weight: 500;
}
.progress-track {
  height: 6px;
  background: #f3f4f6;
  border-radius: 99px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: #3b82f6;
  border-radius: 99px;
}
</style>
