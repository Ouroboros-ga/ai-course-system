<script setup>
import { FileText, MessageCircle, Bot, ArrowRight, Sparkles } from 'lucide-vue-next'
</script>

<template>
  <div class="hero-page slide">
    <div class="split-content">
      <!-- 左侧：文字 + 按钮 -->
      <div class="text-side">
        <div class="badge">
          <Sparkles :size="16" />
          <span>AI 驱动的一站式教学平台</span>
        </div>

        <h1 class="main-title">
          SmartCarb
          <br />
          <span class="gradient-text">
            <span
              v-for="(ch, i) in '实时互动'"
              :key="i"
              class="char"
              :style="{ animationDelay: `${0.2 + i * 0.2}s` }"
            >{{ ch }}</span>
          </span>
        </h1>

        <p class="description">
          免费试用 · 重构课堂体验 · 智能课件 · AI 答疑 · 一站式教学平台
        </p>

        <div class="btn-group">
          <button class="use-btn" @click="$emit('go-chat')">
            免费使用
            <ArrowRight :size="20" class="btn-icon" />
          </button>
        </div>
      </div>

      <!-- 右侧：玻璃态卡片装饰 -->
      <div class="visual-side">
        <div class="glass-hero">
          <div class="glass-card">
            <div class="glass-icon a">
              <FileText :size="24" />
            </div>
            <div class="glass-icon b">
              <MessageCircle :size="24" />
            </div>
            <div class="glass-icon c">
              <Bot :size="24" />
            </div>
          </div>
          <!-- 装饰光晕 -->
          <div class="glow glow-1"></div>
          <div class="glow glow-2"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.slide {
  width: 100%;
  height: calc(100vh - var(--navbar-height));
  scroll-snap-align: start;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 var(--space-12);
}

.hero-page {
  background:
    radial-gradient(circle at 20% 50%, var(--color-primary-light), transparent 45%),
    radial-gradient(circle at 80% 80%, var(--color-secondary-light), transparent 40%),
    var(--color-bg);
}

.split-content {
  display: flex;
  align-items: center;
  gap: var(--space-12);
  width: 100%;
  max-width: 1200px;
}

.text-side {
  flex: 1;
  text-align: left;
}

.visual-side {
  flex: 1;
  display: flex;
  justify-content: center;
}

/* ── 徽章 ── */
.badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-text-secondary);
  box-shadow: var(--shadow-sm);
  margin-bottom: var(--space-6);
}

.badge svg {
  color: var(--color-primary);
}

/* ── 主标题 ── */
.main-title {
  font-size: var(--text-4xl);
  font-weight: var(--font-extrabold);
  line-height: var(--leading-tight);
  margin-bottom: var(--space-6);
  color: var(--color-text);
}

.gradient-text {
  background: var(--gradient-primary);
  background-size: 200% 200%;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: flow 6s var(--ease) infinite;
  display: inline-block;
}

.char {
  display: inline-block;
  opacity: 0;
  transform: translateY(12px);
  animation: charFade var(--duration-slow) var(--ease-spring) forwards;
}

@keyframes flow {
  0% { background-position: 0 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0 50%; }
}

@keyframes charFade {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ── 描述文字 ── */
.description {
  font-size: var(--text-lg);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin-bottom: var(--space-8);
}

/* ── 按钮 ── */
.btn-group {
  display: flex;
  gap: var(--space-4);
}

.use-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-10);
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  border: none;
  border-radius: var(--radius-xl);
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  cursor: pointer;
  box-shadow: var(--shadow-primary);
  transition: var(--transition-all);
}

.use-btn:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
  background: var(--gradient-primary-hover);
}

.btn-icon {
  transition: transform var(--duration-normal) var(--ease);
}

.use-btn:hover .btn-icon {
  transform: translateX(4px);
}

/* ── 右侧玻璃卡片 ── */
.glass-hero {
  width: 100%;
  max-width: 420px;
  height: 380px;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.glass-card {
  width: 280px;
  height: 280px;
  border-radius: var(--radius-2xl);
  background: rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid rgba(255, 255, 255, 0.5);
  box-shadow: var(--shadow-xl);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-5);
  animation: glassEnter var(--duration-slow) var(--ease) forwards,
    floatBreath 6s var(--ease) infinite;
}

.glass-icon {
  width: 56px;
  height: 56px;
  border-radius: var(--radius-lg);
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: iconPop var(--duration-slow) var(--ease-spring) forwards,
    iconFloat 3s var(--ease) infinite;
}

.glass-icon.a { animation-delay: 0.2s, 1.2s; }
.glass-icon.b { animation-delay: 0.4s, 1.4s; }
.glass-icon.c { animation-delay: 0.6s, 1.6s; }

@keyframes glassEnter {
  0% {
    transform: translateY(40px);
    opacity: 0;
  }
  100% {
    transform: translateY(0);
    opacity: 1;
  }
}

@keyframes iconPop {
  0% {
    transform: scale(0);
    opacity: 0;
  }
  100% {
    transform: scale(1);
    opacity: 1;
  }
}

@keyframes floatBreath {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}

@keyframes iconFloat {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}

/* 装饰光晕 */
.glow {
  position: absolute;
  border-radius: var(--radius-full);
  filter: blur(40px);
  z-index: 0;
  pointer-events: none;
}

.glow-1 {
  width: 160px;
  height: 160px;
  background: var(--color-primary-light);
  top: 20px;
  right: 20px;
}

.glow-2 {
  width: 120px;
  height: 120px;
  background: var(--color-secondary-light);
  bottom: 20px;
  left: 20px;
}

/* ── 响应式 ── */
@media (max-width: 1024px) {
  .split-content {
    gap: var(--space-8);
  }
  .glass-hero {
    max-width: 340px;
    height: 320px;
  }
  .glass-card {
    width: 240px;
    height: 240px;
  }
}

@media (max-width: 768px) {
  .slide {
    height: auto;
    min-height: calc(100vh - var(--navbar-height));
    padding: var(--space-12) var(--space-5) var(--space-10);
  }
  .split-content {
    flex-direction: column;
    gap: var(--space-10);
    text-align: center;
  }
  .text-side {
    text-align: center;
  }
  .main-title {
    font-size: var(--text-3xl);
  }
  .description {
    font-size: var(--text-base);
  }
  .btn-group {
    justify-content: center;
  }
  .glass-hero {
    height: 260px;
    max-width: 260px;
  }
  .glass-card {
    width: 200px;
    height: 200px;
    gap: var(--space-3);
  }
  .glass-icon {
    width: 48px;
    height: 48px;
  }
}

@media (max-width: 375px) {
  .main-title {
    font-size: var(--text-2xl);
  }
  .use-btn {
    padding: var(--space-3) var(--space-7);
    font-size: var(--text-base);
  }
}

/* 无障碍：尊重减少动画 */
@media (prefers-reduced-motion: reduce) {
  .glass-card,
  .glass-icon,
  .char,
  .gradient-text,
  .btn-icon {
    animation: none;
  }
  .char {
    opacity: 1;
    transform: none;
  }
  .use-btn:hover {
    transform: none;
  }
}
</style>
