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
          <span class="avatar-icon"><Mic :size="48" /></span>
          <span class="avatar-text">数字人</span>
        </div>
      </slot>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
import { Mic } from 'lucide-vue-next';

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
  z-index: var(--z-modal); /* 最高层级，永远在最上层 */
  width: 280px;
  height: 360px;
  cursor: grab;
  user-select: none;
  transition: box-shadow var(--duration-normal) var(--ease);
}

.draggable-avatar:active {
  cursor: grabbing;
  box-shadow: var(--shadow-lg);
}

.avatar-video-placeholder {
  width: 100%;
  height: 100%;
  border-radius: var(--radius-xl);
  /* 浅色清新渐变 */
  background: var(--color-primary-light);
  box-shadow: var(--shadow-md);
  overflow: hidden;
  border: 1px solid var(--color-border);
}

.avatar-placeholder-content {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  color: var(--color-text-muted); /* 浅灰色文字，更柔和 */
  font-size: var(--text-base);
  font-weight: 500;
}

.avatar-icon {
  display: flex;
  align-items: center;
  color: var(--color-primary);
}

/* 移动端适配：缩小尺寸 */
@media (max-width: 768px) {
  .draggable-avatar {
    width: 200px;
    height: 260px;
  }
  .avatar-placeholder-content {
    font-size: var(--text-sm);
  }
}
</style>
