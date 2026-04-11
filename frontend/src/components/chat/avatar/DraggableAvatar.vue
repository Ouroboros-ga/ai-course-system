<template>
  <div
    ref="avatarRef"
    class="draggable-avatar"
    :style="{ left: `${x}px`, top: `${y}px` }"
    @mousedown="handleMouseDown"
  >
    <!-- 数字人视频占位区 -->
    <div class="avatar-video-placeholder">
      <slot name="video">
        <!-- 外部传入视频组件，这里留空壳 -->
        <div class="avatar-placeholder-content">
          <span class="avatar-icon">🎙️</span>
          <span class="avatar-text">数字人</span>
        </div>
      </slot>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue';

const avatarRef = ref(null);
const x = ref(window.innerWidth - 320); // 初始位置：右侧
const y = ref(200); // 初始位置：垂直居中偏上

let isDragging = false;
let startX = 0;
let startY = 0;

const handleMouseDown = (e) => {
  isDragging = true;
  startX = e.clientX - x.value;
  startY = e.clientY - y.value;
  document.addEventListener('mousemove', handleMouseMove);
  document.addEventListener('mouseup', handleMouseUp);
  // 防止拖动时选中文本
  e.preventDefault();
};

const handleMouseMove = (e) => {
  if (!isDragging) return;
  // 计算新位置，限制在视口内
  const newX = e.clientX - startX;
  const newY = e.clientY - startY;
  const maxX = window.innerWidth - (avatarRef.value?.offsetWidth || 280);
  const maxY = window.innerHeight - (avatarRef.value?.offsetHeight || 360);

  x.value = Math.max(0, Math.min(newX, maxX));
  y.value = Math.max(0, Math.min(newY, maxY));
};

const handleMouseUp = () => {
  isDragging = false;
  document.removeEventListener('mousemove', handleMouseMove);
  document.removeEventListener('mouseup', handleMouseUp);
};

// 窗口 resize 时自动适配位置
const handleResize = () => {
  const maxX = window.innerWidth - (avatarRef.value?.offsetWidth || 280);
  const maxY = window.innerHeight - (avatarRef.value?.offsetHeight || 360);
  x.value = Math.min(x.value, maxX);
  y.value = Math.min(y.value, maxY);
};

onMounted(() => {
  window.addEventListener('resize', handleResize);
});

onUnmounted(() => {
  window.removeEventListener('mousemove', handleMouseMove);
  window.removeEventListener('mouseup', handleMouseUp);
  window.removeEventListener('resize', handleResize);
});
</script>

<style scoped>
.draggable-avatar {
  position: fixed;
  z-index: 99999; /* 最高层级，永远在最上层 */
  width: 280px;
  height: 360px;
  cursor: grab;
  user-select: none;
  transition: box-shadow 0.2s ease;
}

.draggable-avatar:active {
  cursor: grabbing;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
}

.avatar-video-placeholder {
  width: 100%;
  height: 100%;
  border-radius: 20px;
  /* 浅色清新渐变 */
  background: linear-gradient(135deg, #f0f4ff 0%, #f8f0ff 100%);
  box-shadow: 0 4px 16px rgba(129, 140, 248, 0.1);
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.6);
}

.avatar-placeholder-content {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #6b7280; /* 浅灰色文字，更柔和 */
  font-size: 16px;
  font-weight: 500;
}

.avatar-icon {
  font-size: 48px;
  filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.05));
}

/* 移动端适配：缩小尺寸 */
@media (max-width: 768px) {
  .draggable-avatar {
    width: 200px;
    height: 260px;
  }
  .avatar-placeholder-content {
    font-size: 14px;
  }
  .avatar-icon {
    font-size: 36px;
  }
}
</style>
