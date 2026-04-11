<template>
  <div class="ai-control-bar">
    <!-- 左侧：循环 + 倍速 + 音量 -->
    <div class="control-left">
      <button class="btn-icon" @click="emit('loop')" title="循环播放">↺</button>

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

      <!-- 音量控制区域 -->
      <div class="volume-wrapper">
        <button class="btn-icon" @click="toggleVolumeMenu" title="音量">
          {{ volumeIcon }}
        </button>

        <!-- 音量弹出层 -->
        <div class="volume-popup" v-if="showVolumeMenu">
          <!--
            1. 绑定 ref 方便获取 DOM
            2. mousedown 触发拖动开始
          -->
          <div
            class="volume-slider-track"
            ref="volumeTrack"
            @mousedown="startDrag"
          >
            <div class="volume-slider-fill" :style="{ height: volumePercent + '%' }"></div>
            <!-- 小圆球：通过 transform 实现中心对齐 -->
            <div class="volume-slider-thumb" :style="{ bottom: volumePercent + '%' }"></div>
          </div>
          <button class="mute-btn" @click="toggleMute">
            {{ isMuted ? '取消静音' : '静音' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 右侧代码保持不变 -->
    <div class="control-right">
      <button class="btn-play" @click="$emit('toggle')">
        <span v-if="isPlaying">⏸</span>
        <span v-else>▶</span>
      </button>
      <span class="time-display">{{ formatTime(currentTime) }}</span>
      <div class="progress-container" @click="handleSeek">
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
        </div>
      </div>
      <span class="time-display">{{ formatTime(duration) }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onUnmounted } from 'vue';

// Props 定义
const props = defineProps({
  isPlaying: Boolean,
  currentTime: { type: Number, default: 0 },
  duration: { type: Number, default: 0 },
  volume: { type: Number, default: 1 }
});

// Emits 定义
const emit = defineEmits(['toggle', 'loop', 'speed-change', 'volume-change', 'seek']);

// 状态变量
const speed = ref(1.0);
const showSpeedMenu = ref(false);
const showVolumeMenu = ref(false);
const preVolume = ref(1);
const volumeTrack = ref(null); // 获取 DOM 引用

// 计算属性
const progressPercent = computed(() => props.duration ? (props.currentTime / props.duration) * 100 : 0);
const volumePercent = computed(() => props.volume * 100);
const volumeIcon = computed(() => {
  if (props.volume === 0) return '🔇';
  if (props.volume < 0.5) return '🔈';
  return '🔊';
});
const isMuted = computed(() => props.volume === 0);

// --- 拖动逻辑 ---

const updateVolumeFromEvent = (e) => {
  if (!volumeTrack.value) return;
  const rect = volumeTrack.value.getBoundingClientRect();
  const percent = 1 - (e.clientY - rect.top) / rect.height;
  const vol = Math.max(0, Math.min(1, percent));
  emit('volume-change', vol);
};

const startDrag = (e) => {
  e.preventDefault();
  updateVolumeFromEvent(e);
  window.addEventListener('mousemove', onDrag);
  window.addEventListener('mouseup', stopDrag);
};

const onDrag = (e) => {
  updateVolumeFromEvent(e);
};

const stopDrag = () => {
  window.removeEventListener('mousemove', onDrag);
  window.removeEventListener('mouseup', stopDrag);
};

onUnmounted(() => {
  window.removeEventListener('mousemove', onDrag);
  window.removeEventListener('mouseup', stopDrag);
});

// --- 其他功能函数 ---

const formatTime = (seconds) => {
  if (isNaN(seconds) || seconds === Infinity) return '00:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
};

const toggleSpeedMenu = () => {
  showSpeedMenu.value = !showSpeedMenu.value;
  showVolumeMenu.value = false;
};

const changeSpeed = (s) => {
  speed.value = s;
  emit('speed-change', s);
  showSpeedMenu.value = false;
};

const toggleVolumeMenu = () => {
  showVolumeMenu.value = !showVolumeMenu.value;
  showSpeedMenu.value = false;
};

const toggleMute = () => {
  if (isMuted.value) {
    emit('volume-change', preVolume.value || 1);
  } else {
    preVolume.value = props.volume;
    emit('volume-change', 0);
  }
};

const handleSeek = (e) => {
  const rect = e.currentTarget.getBoundingClientRect();
  const percent = (e.clientX - rect.left) / rect.width;
  const seekTime = percent * props.duration;
  emit('seek', seekTime);
};
</script>

<style scoped>
/* ... 大部分样式保持不变 ... */

/* 确保轨道和滑块在拖动时不会选中文字 */
.volume-slider-track,
.volume-slider-thumb {
  user-select: none;
}

.ai-control-bar {
  position: absolute;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  width: 90%;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(8px);
  border-radius: 16px;
  padding: 10px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: 0 10px 25px -5px rgba(37, 99, 235, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.5);
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
  gap: 16px;
  margin-left: 24px;
}

.btn-icon {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 16px;
  color: #6b7280;
  padding: 4px;
  transition: color 0.2s;
}
.btn-icon:hover { color: #2563eb; }

/* 倍速菜单样式 */
.speed-wrapper { position: relative; }
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
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
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
  text-align: left;
}
.speed-menu button.active {
  background: #dbeafe;
  color: #2563eb;
  font-weight: bold;
}

/* 音量控制样式 */
.volume-wrapper { position: relative; }

.volume-popup {
  position: absolute;
  bottom: 30px;
  left: 50%;
  transform: translateX(-50%);
  background: white;
  border-radius: 8px;
  padding: 12px 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  z-index: 10;
  height: 120px;
}

.volume-slider-track {
  width: 6px;
  height: 70px;
  background: #e5e7eb;
  border-radius: 3px;
  position: relative;
  cursor: pointer;
}

.volume-slider-fill {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  background: #2563eb;
  border-radius: 3px;
  pointer-events: none;
}

/* 👇 修改点：使用 transform 进行中心对齐 */
.volume-slider-thumb {
  position: absolute;
  left: 50%;
  /*
    关键修改：
    translate(-50%, 50%) 意味着：
    1. X轴左移自身宽度的50%（水平居中）
    2. Y轴下移自身高度的50%（让中心点对齐进度条位置，而不是底边对齐）
  */
  transform: translate(-50%, 50%);
  width: 12px;
  height: 12px;
  background: #2563eb;
  border-radius: 50%;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
  pointer-events: none;
}

.mute-btn {
  font-size: 10px;
  color: #6b7280;
  background: none;
  border: none;
  cursor: pointer;
  white-space: nowrap;
}
.mute-btn:hover { color: #2563eb; }

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
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
}

.time-display {
  font-size: 12px;
  font-family: monospace;
  color: #6b7280;
  min-width: 40px;
  text-align: center;
}

.progress-container {
  flex: 1;
  height: 20px;
  display: flex;
  align-items: center;
  cursor: pointer;
}

.progress-track {
  width: 100%;
  height: 6px;
  background: #e5e7eb;
  border-radius: 99px;
  overflow: hidden;
  position: relative;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
  border-radius: 99px;
  transition: width 0.1s linear;
}
</style>
