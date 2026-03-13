<!-- src/components/GradientBackground.vue -->
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

/**
 * 🎨 渐变背景组件 (增强版)
 * @prop {String} variant - 变体：'default' | 'light' | 'dark' | 'aurora' | 'sunset' | 'ocean' | 'custom'
 * @prop {Boolean} fixed - 是否固定背景
 * @prop {Boolean} animated - 是否启用动画
 * @prop {Boolean} interactive - 是否启用鼠标交互 (default: true)
 * @prop {Boolean} parallax - 是否启用滚动视差
 */
const props = defineProps({
  variant: {
    type: String,
    default: 'default',
    validator: (v) => ['default', 'light', 'dark', 'aurora', 'sunset', 'ocean', 'custom'].includes(v)
  },
  fixed: {
    type: Boolean,
    default: true
  },
  animated: {
    type: Boolean,
    default: false
  },
  interactive: {
    type: Boolean,
    default: true
  },
  parallax: {
    type: Boolean,
    default: false
  }
})

// 鼠标跟随效果
const mousePos = ref({ x: 0.5, y: 0.5 })
const orbRefs = ref([])
let animationFrameId = null

const handleMouseMove = (e) => {
  if (!props.interactive) return

  const x = e.clientX / window.innerWidth
  const y = e.clientY / window.innerHeight

  mousePos.value = { x, y }
}

// 滚动视差
const scrollY = ref(0)
const handleScroll = () => {
  if (!props.parallax) return
  scrollY.value = window.scrollY
}

onMounted(() => {
  if (props.interactive) {
    window.addEventListener('mousemove', handleMouseMove)
  }
  if (props.parallax) {
    window.addEventListener('scroll', handleScroll, { passive: true })
  }
})

onUnmounted(() => {
  window.removeEventListener('mousemove', handleMouseMove)
  window.removeEventListener('scroll', handleScroll)
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId)
  }
})
</script>

<template>
  <div
    class="gradient-background"
    :class="[
      `variant-${variant}`,
      {
        'is-fixed': fixed,
        'is-animated': animated,
        'is-interactive': interactive
      }
    ]"
    :style="{
      '--mouse-x': mousePos.x,
      '--mouse-y': mousePos.y,
      '--scroll-y': `${scrollY * 0.5}px`
    }"
  >
    <!-- 1. 基础渐变层 -->
    <div class="gradient-base"></div>

    <!-- 2. 径向光晕层 (顶部和底部) -->
    <div class="radial-glow radial-glow--top"></div>
    <div class="radial-glow radial-glow--bottom"></div>

    <!-- 3. 动态噪点层 -->
    <div v-if="animated" class="noise-layer"></div>

    <!-- 4. 演化光球 -->
    <div v-if="animated" class="orb-container">
      <div
        v-for="i in 4"
        :key="i"
        :ref="el => orbRefs[i-1] = el"
        class="evolution-orb"
        :class="`orb-${i}`"
      ></div>
    </div>

    <!-- 5. 网格线装饰层 -->
    <div v-if="variant === 'dark'" class="grid-overlay"></div>

    <!-- 6. 鼠标跟随光晕 -->
    <div v-if="interactive" class="mouse-glow"></div>

    <!-- 7. 内容层 -->
    <div class="content-layer">
      <slot />
    </div>
  </div>
</template>

<style scoped>
/* ═══════════════════════════════════════════════════════════
   🔷 基础容器
   ═══════════════════════════════════════════════════════════ */
.gradient-background {
  position: relative;
  min-height: 100vh;
  width: 100%;
  overflow: hidden;

  /* 默认文字颜色 */
  color: var(--bg-text-color, #0f172a);
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
}

.gradient-background.is-fixed {
  position: fixed;
  top: 0;
  left: 0;
  z-index: -1;
}

/* ═══════════════════════════════════════════════════════════
   🎨 渐变层
   ═══════════════════════════════════════════════════════════ */

/* 基础渐变 */
.gradient-base {
  position: absolute;
  inset: 0;
  background: var(--bg-gradient-main);
  z-index: 0;
  transition: background 0.8s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 径向光晕 */
.radial-glow {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  width: 150%;
  height: 60%;
  pointer-events: none;
  z-index: 1;
  opacity: 0.8;
  transition: opacity 0.5s ease;
}

.radial-glow--top {
  top: -20%;
  background: var(--bg-gradient-top);
}

.radial-glow--bottom {
  bottom: -20%;
  background: var(--bg-gradient-bottom);
}

/* ═══════════════════════════════════════════════════════════
   ✨ 噪点层
   ═══════════════════════════════════════════════════════════ */
.noise-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 2;
  opacity: 0.04;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 512 512' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
  background-size: 200px 200px;
  animation: noiseMove 8s steps(8) infinite;
}

/* ═══════════════════════════════════════════════════════════
   🌈 光球系统
   ═══════════════════════════════════════════════════════════ */
.orb-container {
  position: absolute;
  inset: 0;
  z-index: 3;
  pointer-events: none;
  filter: contrast(1.1);
}

.evolution-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.7;
  mix-blend-mode: var(--orb-blend-mode, overlay);
  will-change: transform;
  backface-visibility: hidden;
}

/* 光球 1：主色光球 - 大范围漂浮 */
.orb-1 {
  width: clamp(300px, 50vw, 600px);
  height: clamp(300px, 50vw, 600px);
  background: radial-gradient(circle, var(--orb-color-1-start) 0%, transparent 70%);
  top: -15%;
  left: -10%;
  animation: orbFloat1 18s ease-in-out infinite;
}

/* 光球 2：副色光球 - 对角移动 */
.orb-2 {
  width: clamp(250px, 45vw, 550px);
  height: clamp(250px, 45vw, 550px);
  background: radial-gradient(circle, var(--orb-color-2-start) 0%, transparent 70%);
  bottom: -20%;
  right: -15%;
  animation: orbFloat2 22s ease-in-out infinite;
}

/* 光球 3：点缀光球 - 中心脉动 */
.orb-3 {
  width: clamp(200px, 35vw, 450px);
  height: clamp(200px, 35vw, 450px);
  background: radial-gradient(circle, var(--orb-color-3-start) 0%, transparent 70%);
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  animation: orbPulse 12s ease-in-out infinite;
}

/* 光球 4：流动光球 - 路径动画 */
.orb-4 {
  width: clamp(150px, 25vw, 350px);
  height: clamp(150px, 25vw, 350px);
  background: radial-gradient(circle, var(--orb-color-4-start, rgba(255, 255, 255, 0.3)) 0%, transparent 70%);
  animation: orbPath 25s linear infinite;
}

/* ═══════════════════════════════════════════════════════════
   🖱️ 鼠标跟随光晕
   ═══════════════════════════════════════════════════════════ */
.mouse-glow {
  position: absolute;
  width: 600px;
  height: 600px;
  border-radius: 50%;
  background: radial-gradient(
    circle,
    rgba(255, 255, 255, 0.15) 0%,
    rgba(255, 255, 255, 0.05) 30%,
    transparent 70%
  );
  left: calc(var(--mouse-x, 0.5) * 100%);
  top: calc(var(--mouse-y, 0.5) * 100%);
  transform: translate(-50%, -50%);
  pointer-events: none;
  z-index: 4;
  opacity: 0;
  transition: opacity 0.3s ease;
}

.gradient-background.is-interactive .mouse-glow {
  opacity: 1;
  transition: left 0.15s ease-out, top 0.15s ease-out, opacity 0.3s ease;
}

/* ═══════════════════════════════════════════════════════════
   📐 网格装饰 (深色主题专用)
   ═══════════════════════════════════════════════════════════ */
.grid-overlay {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
  z-index: 2;
  pointer-events: none;
  transform: translateY(var(--scroll-y, 0));
}

/* ═══════════════════════════════════════════════════════════
   🎬 动画关键帧
   ═══════════════════════════════════════════════════════════ */

/* 噪点移动 */
@keyframes noiseMove {
  0%, 100% { transform: translate(0, 0); }
  12.5% { transform: translate(-5%, -5%); }
  25% { transform: translate(-10%, 0); }
  37.5% { transform: translate(-5%, 5%); }
  50% { transform: translate(0, 10%); }
  62.5% { transform: translate(5%, 5%); }
  75% { transform: translate(10%, 0); }
  87.5% { transform: translate(5%, -5%); }
}

/* 光球浮动动画 - 使用 transform 性能更好 */
@keyframes orbFloat1 {
  0%, 100% {
    transform: translate(0, 0) scale(1);
    filter: blur(80px) brightness(1);
  }
  25% {
    transform: translate(30vw, 20vh) scale(1.15);
  }
  50% {
    transform: translate(20vw, 40vh) scale(0.95);
    filter: blur(100px) brightness(1.1);
  }
  75% {
    transform: translate(-10vw, 30vh) scale(1.1);
  }
}

@keyframes orbFloat2 {
  0%, 100% {
    transform: translate(0, 0) scale(1);
  }
  33% {
    transform: translate(-40vw, -30vh) scale(1.2);
  }
  66% {
    transform: translate(-20vw, -50vh) scale(0.85);
  }
}

@keyframes orbPulse {
  0%, 100% {
    transform: translate(-50%, -50%) scale(0.8);
    opacity: 0.4;
  }
  50% {
    transform: translate(-50%, -50%) scale(1.4);
    opacity: 0.8;
  }
}

/* 光球路径动画 */
@keyframes orbPath {
  0% {
    top: 20%;
    left: 80%;
    opacity: 0;
  }
  10% {
    opacity: 0.6;
  }
  50% {
    top: 80%;
    left: 20%;
    opacity: 0.6;
  }
  90% {
    opacity: 0.6;
  }
  100% {
    top: 20%;
    left: 80%;
    opacity: 0;
  }
}

/* ═══════════════════════════════════════════════════════════
   🎨 主题变体
   ═══════════════════════════════════════════════════════════ */

/* 默认 - 清新蓝调 */
.variant-default {
  --bg-gradient-main: linear-gradient(
    135deg,
    #e0f2fe 0%,
    #f0f9ff 30%,
    #ffffff 50%,
    #f0fdfa 70%,
    #e0f2fe 100%
  );
  --bg-gradient-top: radial-gradient(
    ellipse at 50% -20%,
    rgba(14, 165, 233, 0.25) 0%,
    rgba(56, 189, 248, 0.1) 40%,
    transparent 70%
  );
  --bg-gradient-bottom: radial-gradient(
    ellipse at 50% 120%,
    rgba(20, 184, 166, 0.2) 0%,
    transparent 60%
  );
  --bg-text-color: #0f172a;

  --orb-color-1-start: rgba(56, 189, 248, 0.5);
  --orb-color-2-start: rgba(99, 102, 241, 0.4);
  --orb-color-3-start: rgba(20, 184, 166, 0.35);
  --orb-color-4-start: rgba(168, 85, 247, 0.3);
  --orb-blend-mode: overlay;
}

/* 浅色 - 极简白 */
.variant-light {
  --bg-gradient-main: linear-gradient(
    180deg,
    #ffffff 0%,
    #fafafa 50%,
    #f5f5f5 100%
  );
  --bg-gradient-top: radial-gradient(
    ellipse at 30% 0%,
    rgba(59, 130, 246, 0.08) 0%,
    transparent 50%
  );
  --bg-gradient-bottom: radial-gradient(
    ellipse at 70% 100%,
    rgba(16, 185, 129, 0.06) 0%,
    transparent 50%
  );
  --bg-text-color: #18181b;

  --orb-color-1-start: rgba(59, 130, 246, 0.15);
  --orb-color-2-start: rgba(16, 185, 129, 0.12);
  --orb-color-3-start: rgba(249, 115, 22, 0.1);
  --orb-color-4-start: rgba(168, 85, 247, 0.08);
  --orb-blend-mode: soft-light;
}

/* 深色 - 专业暗夜 */
.variant-dark {
  --bg-gradient-main: linear-gradient(
    145deg,
    #0a0a0a 0%,
    #18181b 25%,
    #1f1f23 50%,
    #18181b 75%,
    #0a0a0a 100%
  );
  --bg-gradient-top: radial-gradient(
    ellipse at 50% -10%,
    rgba(99, 102, 241, 0.15) 0%,
    rgba(56, 189, 248, 0.08) 30%,
    transparent 60%
  );
  --bg-gradient-bottom: radial-gradient(
    ellipse at 50% 110%,
    rgba(168, 85, 247, 0.12) 0%,
    transparent 50%
  );
  --bg-text-color: #fafafa;

  --orb-color-1-start: rgba(99, 102, 241, 0.35);
  --orb-color-2-start: rgba(168, 85, 247, 0.3);
  --orb-color-3-start: rgba(56, 189, 248, 0.25);
  --orb-color-4-start: rgba(236, 72, 153, 0.2);
  --orb-blend-mode: screen;
}

/* 极光 - 梦幻紫绿 */
.variant-aurora {
  --bg-gradient-main: linear-gradient(
    135deg,
    #1e1b4b 0%,
    #312e81 25%,
    #1e3a5f 50%,
    #134e4a 75%,
    #1e1b4b 100%
  );
  --bg-gradient-top: radial-gradient(
    ellipse at 30% -10%,
    rgba(167, 139, 250, 0.4) 0%,
    rgba(99, 102, 241, 0.2) 40%,
    transparent 70%
  );
  --bg-gradient-bottom: radial-gradient(
    ellipse at 70% 110%,
    rgba(52, 211, 153, 0.35) 0%,
    rgba(20, 184, 166, 0.15) 40%,
    transparent 70%
  );
  --bg-text-color: #f5f3ff;

  --orb-color-1-start: rgba(167, 139, 250, 0.6);
  --orb-color-2-start: rgba(52, 211, 153, 0.5);
  --orb-color-3-start: rgba(96, 165, 250, 0.4);
  --orb-color-4-start: rgba(236, 72, 153, 0.35);
  --orb-blend-mode: screen;
}

/* 日落 - 温暖橙红 */
.variant-sunset {
  --bg-gradient-main: linear-gradient(
    135deg,
    #fef3c7 0%,
    #fed7aa 25%,
    #fecaca 50%,
    #fbcfe8 75%,
    #e9d5ff 100%
  );
  --bg-gradient-top: radial-gradient(
    ellipse at 70% 0%,
    rgba(251, 146, 60, 0.3) 0%,
    rgba(249, 115, 22, 0.15) 40%,
    transparent 70%
  );
  --bg-gradient-bottom: radial-gradient(
    ellipse at 30% 100%,
    rgba(236, 72, 153, 0.25) 0%,
    rgba(168, 85, 247, 0.1) 40%,
    transparent 70%
  );
  --bg-text-color: #431407;

  --orb-color-1-start: rgba(251, 146, 60, 0.45);
  --orb-color-2-start: rgba(236, 72, 153, 0.4);
  --orb-color-3-start: rgba(249, 115, 22, 0.35);
  --orb-color-4-start: rgba(168, 85, 247, 0.3);
  --orb-blend-mode: overlay;
}

/* 海洋 - 深邃蓝绿 */
.variant-ocean {
  --bg-gradient-main: linear-gradient(
    135deg,
    #0c4a6e 0%,
    #075985 25%,
    #0369a1 50%,
    #0e7490 75%,
    #155e75 100%
  );
  --bg-gradient-top: radial-gradient(
    ellipse at 50% -20%,
    rgba(14, 165, 233, 0.3) 0%,
    rgba(56, 189, 248, 0.15) 40%,
    transparent 70%
  );
  --bg-gradient-bottom: radial-gradient(
    ellipse at 50% 120%,
    rgba(20, 184, 166, 0.25) 0%,
    transparent 60%
  );
  --bg-text-color: #ecfeff;

  --orb-color-1-start: rgba(56, 189, 248, 0.5);
  --orb-color-2-start: rgba(20, 184, 166, 0.45);
  --orb-color-3-start: rgba(34, 211, 238, 0.35);
  --orb-color-4-start: rgba(99, 102, 241, 0.3);
  --orb-blend-mode: screen;
}

/* 自定义变体 */
.variant-custom {
  /* 所有变量通过 style 或外部 CSS 覆盖 */
}

/* ═══════════════════════════════════════════════════════════
   📱 响应式适配
   ═══════════════════════════════════════════════════════════ */
@media (max-width: 1024px) {
  .evolution-orb {
    filter: blur(60px);
  }

  .orb-1, .orb-2 {
    width: clamp(200px, 60vw, 400px);
    height: clamp(200px, 60vw, 400px);
  }

  .orb-3 {
    width: clamp(150px, 40vw, 300px);
    height: clamp(150px, 40vw, 300px);
  }
}

@media (max-width: 640px) {
  .evolution-orb {
    filter: blur(40px);
    opacity: 0.5;
  }

  .orb-4 {
    display: none; /* 移动端隐藏第4个光球 */
  }

  .mouse-glow {
    display: none; /* 移动端隐藏鼠标跟随 */
  }

  .radial-glow {
    width: 200%;
    opacity: 0.6;
  }
}

/* ═══════════════════════════════════════════════════════════
   ♿ 无障碍 - 尊重减少动画偏好
   ═══════════════════════════════════════════════════════════ */
@media (prefers-reduced-motion: reduce) {
  .evolution-orb,
  .noise-layer,
  .mouse-glow {
    animation: none !important;
    transition: none !important;
  }

  .evolution-orb {
    opacity: 0.3;
  }
}

/* ═══════════════════════════════════════════════════════════
   📦 内容层
   ═══════════════════════════════════════════════════════════ */
.content-layer {
  position: relative;
  z-index: 10;
  height: 100%;
  width: 100%;
}
</style>
