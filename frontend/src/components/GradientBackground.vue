<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  variant: {
    type: String,
    default: 'default',
    validator: (v) => ['default', 'light', 'dark', 'aurora'].includes(v)
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
    default: false
  },
})

const mousePos = ref({ x: 0.5, y: 0.5 })

const handleMouseMove = (e) => {
  if (!props.interactive) return
  mousePos.value = {
    x: e.clientX / window.innerWidth,
    y: e.clientY / window.innerHeight
  }
}

onMounted(() => {
  if (props.interactive) {
    window.addEventListener('mousemove', handleMouseMove, { passive: true })
  }
})

onUnmounted(() => {
  window.removeEventListener('mousemove', handleMouseMove)
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
      }
    ]"
    :style="{
      '--mouse-x': mousePos.x,
      '--mouse-y': mousePos.y,
    }"
  >
    <div class="gradient-base"></div>
    <div class="radial-glow radial-glow--top"></div>
    <div class="radial-glow radial-glow--bottom"></div>

    <!-- 精简为 2 个光球（性能优化） -->
    <template v-if="animated">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
    </template>

    <!-- 鼠标跟随光晕（仅桌面端） -->
    <div v-if="interactive" class="mouse-glow"></div>

    <!-- 内容层 -->
    <div class="content-layer">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.gradient-background {
  position: relative;
  min-height: 100vh;
  width: 100%;
  overflow: hidden;
  color: var(--color-text);
  font-family: var(--font-sans);
}

.gradient-background.is-fixed {
  position: fixed;
  top: 0;
  left: 0;
  z-index: -1;
}

/* 渐变层 */
.gradient-base {
  position: absolute;
  inset: 0;
  background: var(--bg-gradient-main);
  z-index: 0;
  transition: background var(--duration-slow) var(--ease);
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
}

.radial-glow--top {
  top: -20%;
  background: var(--bg-gradient-top);
}

.radial-glow--bottom {
  bottom: -20%;
  background: var(--bg-gradient-bottom);
}

/* 光球系统（精简为 2 个） */
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.6;
  will-change: transform;
  backface-visibility: hidden;
}

.orb-1 {
  width: clamp(300px, 50vw, 600px);
  height: clamp(300px, 50vw, 600px);
  background: radial-gradient(circle, var(--orb-color-1) 0%, transparent 70%);
  top: -15%;
  left: -10%;
  animation: orbFloat1 20s ease-in-out infinite;
}

.orb-2 {
  width: clamp(250px, 45vw, 550px);
  height: clamp(250px, 45vw, 550px);
  background: radial-gradient(circle, var(--orb-color-2) 0%, transparent 70%);
  bottom: -20%;
  right: -15%;
  animation: orbFloat2 24s ease-in-out infinite;
}

/* 鼠标跟随光晕 */
.mouse-glow {
  position: absolute;
  width: 600px;
  height: 600px;
  border-radius: 50%;
  background: radial-gradient(
    circle,
    rgba(255, 255, 255, 0.1) 0%,
    transparent 70%
  );
  left: calc(var(--mouse-x, 0.5) * 100%);
  top: calc(var(--mouse-y, 0.5) * 100%);
  transform: translate(-50%, -50%);
  pointer-events: none;
  z-index: 2;
  transition: left 0.15s ease-out, top 0.15s ease-out;
}

/* 内容层 */
.content-layer {
  position: relative;
  z-index: 10;
  height: 100%;
  width: 100%;
}

/* 动画 */
@keyframes orbFloat1 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(20vw, 30vh) scale(1.1); }
}

@keyframes orbFloat2 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(-30vw, -20vh) scale(0.9); }
}

/* 主题变体 */
.variant-default {
  --bg-gradient-main: linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 30%, #ffffff 50%, #f0fdfa 70%, #e0f2fe 100%);
  --bg-gradient-top: radial-gradient(ellipse at 50% -20%, rgba(14, 165, 233, 0.2) 0%, transparent 70%);
  --bg-gradient-bottom: radial-gradient(ellipse at 50% 120%, rgba(20, 184, 166, 0.15) 0%, transparent 60%);
  --orb-color-1: rgba(56, 189, 248, 0.4);
  --orb-color-2: rgba(99, 102, 241, 0.35);
}

.variant-light {
  --bg-gradient-main: linear-gradient(180deg, #ffffff 0%, #fafafa 50%, #f5f5f5 100%);
  --bg-gradient-top: radial-gradient(ellipse at 30% 0%, rgba(99, 102, 241, 0.06) 0%, transparent 50%);
  --bg-gradient-bottom: radial-gradient(ellipse at 70% 100%, rgba(16, 185, 129, 0.05) 0%, transparent 50%);
  --orb-color-1: rgba(99, 102, 241, 0.12);
  --orb-color-2: rgba(16, 185, 129, 0.1);
}

.variant-dark {
  --bg-gradient-main: linear-gradient(145deg, #0a0a0a 0%, #18181b 50%, #0a0a0a 100%);
  --bg-gradient-top: radial-gradient(ellipse at 50% -10%, rgba(99, 102, 241, 0.12) 0%, transparent 60%);
  --bg-gradient-bottom: radial-gradient(ellipse at 50% 110%, rgba(168, 85, 247, 0.1) 0%, transparent 50%);
  --orb-color-1: rgba(99, 102, 241, 0.3);
  --orb-color-2: rgba(168, 85, 247, 0.25);
}

.variant-aurora {
  --bg-gradient-main: linear-gradient(135deg, #1e1b4b 0%, #312e81 25%, #1e3a5f 50%, #134e4a 75%, #1e1b4b 100%);
  --bg-gradient-top: radial-gradient(ellipse at 30% -10%, rgba(167, 139, 250, 0.3) 0%, transparent 70%);
  --bg-gradient-bottom: radial-gradient(ellipse at 70% 110%, rgba(52, 211, 153, 0.25) 0%, transparent 70%);
  --orb-color-1: rgba(167, 139, 250, 0.5);
  --orb-color-2: rgba(52, 211, 153, 0.4);
}

/* 响应式 */
@media (max-width: 768px) {
  .orb {
    filter: blur(50px);
    opacity: 0.4;
  }

  .orb-1, .orb-2 {
    width: clamp(200px, 60vw, 400px);
    height: clamp(200px, 60vw, 400px);
  }

  .mouse-glow {
    display: none;
  }
}

/* 无障碍 */
@media (prefers-reduced-motion: reduce) {
  .orb {
    animation: none !important;
    opacity: 0.2;
  }
}
</style>
