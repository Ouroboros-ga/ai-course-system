<template>
  <div class="ai-control-bar">
    <!-- 左侧：循环 + 倍速 + 音量 -->
    <div class="control-left">
      <button class="btn-icon" @click="emit('loop')" title="循环播放"><RotateCcw :size="16" /></button>

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
          <component :is="volumeIcon" :size="16" />
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
        <Pause v-if="isPlaying" :size="16" />
        <Play v-else :size="16" />
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
import { RotateCcw, Pause, Play, VolumeX, Volume1, Volume2 } from 'lucide-vue-next';

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
  if (props.volume === 0) return VolumeX;
  if (props.volume < 0.5) return Volume1;
  return Volume2;
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
  bottom: var(--space-4);
  left: 50%;
  transform: translateX(-50%);
  width: 90%;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(8px);
  border-radius: var(--radius-xl);
  padding: var(--space-2) var(--space-5);
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: var(--shadow-primary);
  border: 1px solid var(--color-border);
}

.control-left {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.control-right {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-left: var(--space-6);
}

.btn-icon {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--color-text-muted);
  padding: var(--space-1);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color var(--duration-normal) var(--ease);
}
.btn-icon:hover { color: var(--color-primary); }

/* 倍速菜单样式 */
.speed-wrapper { position: relative; }
.speed-tag {
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  background: var(--color-surface-2);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  border: none;
  cursor: pointer;
  color: var(--color-text-secondary);
}

.speed-menu {
  position: absolute;
  bottom: 30px;
  left: 0;
  background: var(--color-surface);
  border-radius: var(--radius-md);
  padding: var(--space-1);
  box-shadow: var(--shadow-md);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  z-index: var(--z-overlay);
}
.speed-menu button {
  background: none;
  border: none;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--text-xs);
  text-align: left;
  color: var(--color-text-secondary);
}
.speed-menu button.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-weight: bold;
}

/* 音量控制样式 */
.volume-wrapper { position: relative; }

.volume-popup {
  position: absolute;
  bottom: 30px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--color-surface);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-2);
  box-shadow: var(--shadow-md);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  z-index: var(--z-overlay);
  height: 120px;
}

.volume-slider-track {
  width: 6px;
  height: 70px;
  background: var(--color-border);
  border-radius: var(--radius-full);
  position: relative;
  cursor: pointer;
}

.volume-slider-fill {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  background: var(--color-primary);
  border-radius: var(--radius-full);
  pointer-events: none;
}

/* 使用 transform 进行中心对齐 */
.volume-slider-thumb {
  position: absolute;
  left: 50%;
  transform: translate(-50%, 50%);
  width: 12px;
  height: 12px;
  background: var(--color-primary);
  border-radius: var(--radius-full);
  box-shadow: var(--shadow-sm);
  pointer-events: none;
}

.mute-btn {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  background: none;
  border: none;
  cursor: pointer;
  white-space: nowrap;
  transition: color var(--duration-normal) var(--ease);
}
.mute-btn:hover { color: var(--color-primary); }

.btn-play {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-full);
  background: var(--color-primary);
  color: var(--color-text-inverse);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: var(--shadow-primary);
  transition: background var(--duration-normal) var(--ease);
}

.btn-play:hover {
  background: var(--color-primary-hover);
}

.time-display {
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  color: var(--color-text-muted);
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
  background: var(--color-border);
  border-radius: var(--radius-full);
  overflow: hidden;
  position: relative;
}

.progress-fill {
  height: 100%;
  background: var(--gradient-primary);
  border-radius: var(--radius-full);
  transition: width 0.1s linear;
}
</style>
