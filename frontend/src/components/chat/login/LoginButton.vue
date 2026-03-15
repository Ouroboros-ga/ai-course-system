<script setup>
import AvatarIcon from '@/assets/Avatar.svg'

const emit = defineEmits(['click'])

const handleClick = () => {
  emit('click')
}
</script>

<template>
  <button class="login-btn" @click="handleClick">
    <!-- 图标 -->
    <img :src="AvatarIcon" alt="Login" class="icon" />

    <!-- 背景光效层 -->
    <span class="glow-layer"></span>
  </button>
</template>

<style scoped>
.login-btn {
  position: absolute;
  right: 20px;
  top: 20px;

  display: flex;
  align-items: center;
  justify-content: center;

  width: 48px;
  height: 48px;
  padding: 0;

  border-radius: 50%;
  border: none;

  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);

  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);

  cursor: pointer;
  overflow: hidden;

  transition: all 0.3s ease;
}


/* 图标样式 */
.icon {
  width: 22px;
  height: 22px;

  /* 强制变白 */
  filter: brightness(0) invert(1);
  opacity: 0.9;

  /* 层级要在光效之上 */
  position: relative;
  z-index: 2;

  transition: transform 0.3s ease;
}

/* 光效层 */
.glow-layer {
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(
    120deg,
    transparent,
    rgba(255, 255, 255, 0.4),
    transparent
  );
  z-index: 1;
  transition: left 0.5s ease;
}

/* --- 交互 --- */

/* 悬停 */
.login-btn:hover {
  transform: translateY(-2px) scale(1.05);
  box-shadow: 0 6px 16px rgba(102, 126, 234, 0.5);
}

.login-btn:hover .icon {
  transform: rotate(15deg);
}

.login-btn:hover .glow-layer {
  left: 100%;
}

/* 点击 */
.login-btn:active {
  transform: scale(0.95);
  box-shadow: 0 2px 8px rgba(102, 126, 234, 0.4);
}
</style>
