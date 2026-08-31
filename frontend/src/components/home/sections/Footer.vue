<script setup>
import { GraduationCap, ArrowRight } from 'lucide-vue-next'

const linkGroups = [
  {
    title: '产品',
    links: [
      { label: 'AI 课件', href: '#' },
      { label: '实时答疑', href: '#' },
      { label: '知识图谱', href: '#' },
      { label: '数字人', href: '#' },
    ],
  },
  {
    title: '资源',
    links: [
      { label: '使用文档', href: '#' },
      { label: 'API 接口', href: '#' },
      { label: '常见问题', href: '#' },
      { label: '更新日志', href: '#' },
    ],
  },
  {
    title: '关于',
    links: [
      { label: '关于我们', href: '#' },
      { label: '使用协议', href: '#' },
      { label: '隐私政策', href: '#' },
      { label: '联系方式', href: '#' },
    ],
  },
]
</script>

<template>
  <section class="slide footer-section">
    <!-- CTA 区 -->
    <div class="cta-area">
      <h2 class="cta-title">
        立即开启你的
        <span class="gradient-text">CodeNexus智码交响</span>
        之旅
      </h2>
      <p class="cta-desc">免费试用，无需注册，即刻体验智能教学新方式</p>
      <button class="use-btn" @click="$emit('go-chat')">
        立即使用
        <ArrowRight :size="20" class="btn-icon" />
      </button>
    </div>

    <!-- 页脚主体 -->
    <footer class="footer-main">
      <div class="footer-content">
        <!-- Logo + 简介 -->
        <div class="footer-brand">
          <div class="brand-logo">
            <GraduationCap :size="28" class="logo-icon" />
            <span class="logo-text">CodeNexus智码交响</span>
          </div>
          <p class="brand-desc">
            计算机学科垂类大模型驱动的智能教学系统，让每一次学习都更高效。
          </p>
        </div>

        <!-- 链接列 -->
        <div class="footer-links">
          <div
            v-for="(group, i) in linkGroups"
            :key="i"
            class="link-col"
          >
            <h4 class="link-title">{{ group.title }}</h4>
            <a
              v-for="(link, j) in group.links"
              :key="j"
              :href="link.href"
              class="link-item"
            >
              {{ link.label }}
            </a>
          </div>
        </div>
      </div>

      <!-- 版权栏 -->
      <div class="footer-bottom">
        <p>© 2026 CodeNexus智码交响 · 知识图谱驱动的智能教学系统</p>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.slide {
  width: 100%;
  min-height: calc(100vh - var(--navbar-height));
  scroll-snap-align: start;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  position: relative;
}

.footer-section {
  background:
    radial-gradient(circle at 20% 30%, var(--color-primary-light), transparent 45%),
    radial-gradient(circle at 80% 70%, var(--color-secondary-light), transparent 40%),
    var(--color-bg);
}

/* ── CTA 区 ── */
.cta-area {
  text-align: center;
  padding: var(--space-12) var(--space-8) var(--space-10);
  max-width: 700px;
  margin: 0 auto;
}

.cta-title {
  font-size: var(--text-4xl);
  font-weight: var(--font-extrabold);
  line-height: var(--leading-tight);
  margin-bottom: var(--space-5);
  color: var(--color-text);
}

.gradient-text {
  background: var(--gradient-primary);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.cta-desc {
  font-size: var(--text-lg);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin-bottom: var(--space-8);
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

/* ── 页脚主体 ── */
.footer-main {
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
  padding: var(--space-8) var(--space-12) var(--space-5);
}

.footer-content {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  gap: var(--space-10);
  flex-wrap: wrap;
}

.footer-brand {
  flex: 0 0 280px;
}

.brand-logo {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.logo-icon {
  color: var(--color-primary);
}

.logo-text {
  font-size: var(--text-xl);
  font-weight: var(--font-extrabold);
  color: var(--color-text);
}

.brand-desc {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin: 0;
}

.footer-links {
  display: flex;
  gap: var(--space-10);
}

.link-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.link-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-text);
  margin: 0 0 var(--space-2);
}

.link-item {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  text-decoration: none;
  cursor: pointer;
  transition: var(--transition-color);
}

.link-item:hover {
  color: var(--color-primary);
}

/* ── 版权栏 ── */
.footer-bottom {
  max-width: 1200px;
  margin: var(--space-6) auto 0;
  padding-top: var(--space-5);
  border-top: 1px solid var(--color-border);
  text-align: center;
}

.footer-bottom p {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin: 0;
}

/* ── 响应式 ── */
@media (max-width: 1024px) {
  .cta-title {
    font-size: var(--text-3xl);
  }
  .footer-content {
    gap: var(--space-8);
  }
}

@media (max-width: 768px) {
  .slide {
    min-height: auto;
  }
  .cta-area {
    padding: var(--space-10) var(--space-5) var(--space-8);
  }
  .cta-title {
    font-size: var(--text-2xl);
  }
  .cta-desc {
    font-size: var(--text-base);
  }
  .footer-main {
    padding: var(--space-8) var(--space-5) var(--space-5);
  }
  .footer-content {
    flex-direction: column;
    gap: var(--space-6);
  }
  .footer-brand {
    flex: none;
  }
  .footer-links {
    gap: var(--space-6);
    flex-wrap: wrap;
  }
}

@media (max-width: 375px) {
  .cta-title {
    font-size: var(--text-xl);
  }
  .use-btn {
    padding: var(--space-3) var(--space-7);
    font-size: var(--text-base);
  }
  .footer-links {
    flex-direction: column;
    gap: var(--space-5);
  }
}

/* 无障碍 */
@media (prefers-reduced-motion: reduce) {
  .use-btn:hover {
    transform: none;
  }
  .btn-icon {
    transition: none;
  }
}
</style>
