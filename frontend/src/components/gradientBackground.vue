<!-- src/components/GradientBackground.vue -->
<script setup>
/**
 * 🎨 渐变背景组件 (强演化动画版)
 * @prop {String} variant - 变体：'default' | 'light' | 'dark' | 'custom'
 * @prop {Boolean} fixed - 是否固定背景 (default: true)
 * @prop {Boolean} animated - 是否启用强演化动画 (default: false)
 */
const props = defineProps({
  variant: {
    type: String,
    default: 'default',
    validator: (v) => ['default', 'light', 'dark', 'custom'].includes(v)
  },
  fixed: {
    type: Boolean,
    default: true
  },
  animated: {
    type: Boolean,
    default: false
  }
})
</script>

<template>
  <div
    class="gradient-background"
    :class="[
      `variant-${variant}`,
      { 'is-fixed': fixed, 'is-animated': animated }
    ]"
  >
    <!-- 1. 动态噪点层 (增加质感) -->
    <div v-if="animated" class="noise-layer"></div>

    <!-- 2. 演化光球 (色彩 + 位置双重演化) -->
    <div v-if="animated" class="evolution-orb orb-1"></div>
    <div v-if="animated" class="evolution-orb orb-2"></div>
    <div v-if="animated" class="evolution-orb orb-3"></div>

    <!-- 3. 内容层 -->
    <div class="content-layer">
      <slot />
    </div>
  </div>
</template>

<style scoped>
/* 🔷 基础容器 */
.gradient-background {
  position: relative;
  min-height: 100vh;
  width: 100%;
  overflow: hidden;

  /* 基础背景变量 (fallback) */
  --bg-gradient-main: linear-gradient(135deg, #e3f0ff 0%, #f8fafc 50%, #e8fcff 100%);
  --bg-gradient-top: radial-gradient(ellipse at 50% 0%, rgba(14, 165, 233, 0.35) 0%, rgba(50, 176, 232, 0.15) 30%, transparent 75%);
  --bg-gradient-bottom: radial-gradient(ellipse at 50% 100%, rgba(245, 249, 251, 0.3) 0%, rgba(56, 189, 248, 0.12) 35%, transparent 70%);
  --bg-text-color: #0f172a;

  /* 光球变量 (fallback) */
  --orb-color-1-start: rgba(56, 189, 248, 0.6);
  --orb-color-1-end: rgba(14, 165, 233, 0.4);
  --orb-color-2-start: rgba(99, 102, 241, 0.5);
  --orb-color-2-end: rgba(139, 92, 246, 0.3);
  --orb-color-3-start: rgba(236, 72, 153, 0.3);
  --orb-blend-mode: overlay;

  /* 应用背景 */
  background-image:
    var(--bg-gradient-main),
    var(--bg-gradient-top),
    var(--bg-gradient-bottom);

  background-size: 200% 200%, 150% 150%, 150% 150%;
  background-position: 0 0, 50% 0%, 50% 100%;
  background-repeat: no-repeat;

  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  color: var(--bg-text-color);
  transition: background-color 0.5s ease;
}

/* 🔧 定位 */
.gradient-background.is-fixed {
  position: fixed;
  top: 0;
  left: 0;
  z-index: -1;
}

.content-layer {
  position: relative;
  z-index: 10;
  height: 100%;
  width: 100%;
}

/* ✨ 1. 动态噪点层 (关键质感来源) */
.noise-layer {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 1;
  opacity: 0.07;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E");
  animation: noiseShift 10s steps(10) infinite;
}

/* ✨ 2. 演化光球通用样式 */
.evolution-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(60px);
  opacity: 0.8;
  z-index: 0;
  pointer-events: none;
  will-change: transform, background-color;
  mix-blend-mode: var(--orb-blend-mode);
}

/* 光球 1：左上 -> 右下 (大尺寸，慢速) */
.orb-1 {
  width: 60vw;
  height: 60vw;
  background: var(--orb-color-1-start);
  top: -20%;
  left: -20%;
  animation:
    floatOrb1 15s ease-in-out infinite alternate,
    colorShift1 10s ease-in-out infinite alternate;
}

/* 光球 2：右下 -> 左上 (中尺寸，中速) */
.orb-2 {
  width: 50vw;
  height: 50vw;
  background: var(--orb-color-2-start);
  bottom: -20%;
  right: -20%;
  animation:
    floatOrb2 20s ease-in-out infinite alternate-reverse,
    colorShift2 12s ease-in-out infinite alternate-reverse;
}

/* 光球 3：中心呼吸 (小尺寸，快速) */
.orb-3 {
  width: 40vw;
  height: 40vw;
  background: var(--orb-color-3-start);
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  animation:
    pulseOrb3 8s ease-in-out infinite,
    colorShift3 15s linear infinite;
}

/* ✨ 3. 强演化动画激活状态 */
.gradient-background.is-animated {
  animation: bgRotate 30s linear infinite;
}

/* 🎬 关键帧定义 */

/* 背景旋转 */
@keyframes bgRotate {
  0% { background-position: 0% 0%, 50% 0%, 50% 100%; }
  50% { background-position: 100% 100%, 60% 10%, 40% 90%; }
  100% { background-position: 0% 0%, 50% 0%, 50% 100%; }
}

/* 噪点移动 */
@keyframes noiseShift {
  0%, 100% { background-position: 0 0; }
  10% { background-position: 5% 5%; }
  20% { background-position: 10% 0%; }
  30% { background-position: 5% 10%; }
  40% { background-position: 15% 5%; }
  50% { background-position: 10% 15%; }
  60% { background-position: 5% 10%; }
  70% { background-position: 15% 0%; }
  80% { background-position: 0% 15%; }
  90% { background-position: 10% 5%; }
}

/* 光球位置移动 */
@keyframes floatOrb1 {
  0% { transform: translate(0, 0) scale(1); }
  100% { transform: translate(40vw, 50vh) scale(1.2); }
}

@keyframes floatOrb2 {
  0% { transform: translate(0, 0) scale(1); }
  100% { transform: translate(-50vw, -40vh) scale(0.9); }
}

@keyframes pulseOrb3 {
  0%, 100% { transform: translate(-50%, -50%) scale(0.8); opacity: 0.4; }
  50% { transform: translate(-50%, -50%) scale(1.3); opacity: 0.7; }
}

/* 光球颜色演化 */
@keyframes colorShift1 {
  0% { background-color: var(--orb-color-1-start); }
  100% { background-color: var(--orb-color-1-end); }
}

@keyframes colorShift2 {
  0% { background-color: var(--orb-color-2-start); }
  100% { background-color: var(--orb-color-2-end); }
}

@keyframes colorShift3 {
  0% { filter: hue-rotate(0deg) blur(60px); }
  50% { filter: hue-rotate(40deg) blur(70px); }
  100% { filter: hue-rotate(0deg) blur(60px); }
}

/* 🎨 变体系统 (完整定义所有变量) */

/* 默认变体 */
.variant-default {
  --bg-gradient-main: linear-gradient(135deg, #e3f0ff 0%, #f8fafc 50%, #e8fcff 100%);
  --bg-gradient-top: radial-gradient(ellipse at 50% 0%, rgba(14, 165, 233, 0.35) 0%, rgba(50, 176, 232, 0.15) 30%, transparent 75%);
  --bg-gradient-bottom: radial-gradient(ellipse at 50% 100%, rgba(245, 249, 251, 0.3) 0%, rgba(56, 189, 248, 0.12) 35%, transparent 70%);
  --bg-text-color: #0f172a;

  --orb-color-1-start: rgba(56, 189, 248, 0.6);
  --orb-color-1-end: rgba(14, 165, 233, 0.4);
  --orb-color-2-start: rgba(99, 102, 241, 0.5);
  --orb-color-2-end: rgba(139, 92, 246, 0.3);
  --orb-color-3-start: rgba(236, 72, 153, 0.3);
  --orb-blend-mode: overlay;
}

/* 浅色变体 */
.variant-light {
  --bg-gradient-main: linear-gradient(135deg, #f0f9ff 0%, #ffffff 50%, #f0fdfa 100%);
  --bg-gradient-top: radial-gradient(ellipse at 50% 0%, rgba(14, 165, 233, 0.2) 0%, transparent 60%);
  --bg-gradient-bottom: radial-gradient(ellipse at 50% 100%, rgba(20, 184, 166, 0.15) 0%, transparent 65%);
  --bg-text-color: #0f172a;

  --orb-color-1-start: rgba(45, 212, 191, 0.5);
  --orb-color-1-end: rgba(56, 189, 248, 0.3);
  --orb-color-2-start: rgba(251, 146, 60, 0.4);
  --orb-color-2-end: rgba(239, 68, 68, 0.2);
  --orb-color-3-start: rgba(34, 197, 94, 0.3);
  --orb-blend-mode: soft-light;
}

/* 深色变体 */
.variant-dark {
  --bg-gradient-main: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
  --bg-gradient-top: radial-gradient(ellipse at 50% 0%, rgba(56, 189, 248, 0.25) 0%, transparent 70%);
  --bg-gradient-bottom: radial-gradient(ellipse at 50% 100%, rgba(14, 165, 233, 0.2) 0%, transparent 70%);
  --bg-text-color: #f1f5f9;

  --orb-color-1-start: rgba(56, 189, 248, 0.4);
  --orb-color-1-end: rgba(167, 139, 250, 0.3);
  --orb-color-2-start: rgba(139, 92, 246, 0.4);
  --orb-color-2-end: rgba(236, 72, 153, 0.2);
  --orb-color-3-start: rgba(56, 189, 248, 0.3);
  --orb-blend-mode: screen;
}

/* 自定义变体 (允许外部完全覆盖) */
.variant-custom {
  /* 所有变量可通过外部 CSS 或 style 属性传入 */
}

/* 📱 响应式优化 */
@media (max-width: 768px) {
  .evolution-orb {
    filter: blur(40px);
  }
  .orb-1 { width: 80vw; height: 80vw; }
  .orb-2 { width: 80vw; height: 80vw; }
  .orb-3 { width: 60vw; height: 60vw; }
}

/* ♿ 减少动画偏好 */
@media (prefers-reduced-motion: reduce) {
  .gradient-background.is-animated {
    animation: none;
  }
  .evolution-orb, .noise-layer {
    animation: none;
    opacity: 0.2;
  }
}
</style>
