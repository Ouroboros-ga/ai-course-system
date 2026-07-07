<script setup>
import { ref } from 'vue'
import {
  FileText,
  MessageCircle,
  Network,
  Video,
  TrendingUp,
  Brain,
  Heart,
  ArrowRight,
} from 'lucide-vue-next'

const features = [
  {
    icon: FileText,
    title: 'AI 课件生成',
    desc: '上传文档自动生成结构化课件，信息完整、排版规范。',
  },
  {
    icon: MessageCircle,
    title: '实时问答',
    desc: '随时提问，AI 结合课件精准回答，支持语音交互。',
  },
  {
    icon: Network,
    title: '知识图谱',
    desc: '自动构建学科知识网络，可视化呈现知识点关联。',
  },
  {
    icon: Video,
    title: '数字人视频',
    desc: 'AI 数字人逐页讲解课件，打造沉浸式学习体验。',
  },
  {
    icon: TrendingUp,
    title: '学习进度',
    desc: '清晰记录学习轨迹，智能续接上次进度不停顿。',
  },
  {
    icon: Brain,
    title: '认知分析',
    desc: '多维度分析学习行为，精准定位薄弱知识点。',
  },
]

const liked = ref(features.map(() => true))

const toggleLike = (index) => {
  liked.value[index] = !liked.value[index]
}

const goToChat = () => {
  window.location.href = 'http://localhost:5173/chat#/chat'
}
</script>

<template>
  <div class="feature-section slide">
    <!-- 标题区 -->
    <div class="feature-header">
      <span class="eyebrow">核心功能</span>
      <h2 class="section-title">开启智能学习时代</h2>
      <p class="section-subtitle">AI 伴学，让每一次学习都更高效</p>
    </div>

    <!-- 卡片网格 -->
    <div class="feature-grid">
      <div
        v-for="(item, index) in features"
        :key="index"
        class="feature-card"
      >
        <div class="card-icon">
          <component :is="item.icon" :size="26" />
        </div>
        <h3 class="card-title">{{ item.title }}</h3>
        <p class="card-desc">{{ item.desc }}</p>
        <div class="card-actions">
          <button
            class="action-btn heart-btn"
            :aria-label="liked[index] ? '取消收藏' : '收藏'"
            @click="toggleLike(index)"
          >
            <Heart
              :size="18"
              :fill="liked[index] ? 'currentColor' : 'none'"
            />
          </button>
          <button
            class="action-btn"
            aria-label="前往体验"
            @click="goToChat"
          >
            <ArrowRight :size="18" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.feature-section {
  width: 100%;
  min-height: calc(100vh - var(--navbar-height));
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-10) var(--space-8);
  background: var(--color-surface);
  gap: var(--space-10);
}

/* ── 标题区 ── */
.feature-header {
  text-align: center;
  max-width: 600px;
}

.eyebrow {
  display: inline-block;
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-primary);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: var(--space-3);
}

.section-title {
  font-size: var(--text-4xl);
  font-weight: var(--font-extrabold);
  color: var(--color-text);
  line-height: var(--leading-tight);
  margin: 0 0 var(--space-4);
}

.section-subtitle {
  font-size: var(--text-xl);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin: 0;
}

/* ── 卡片网格 ── */
.feature-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-5);
  width: 100%;
  max-width: 1024px;
}

.feature-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  padding: var(--space-7) var(--space-6);
  display: flex;
  flex-direction: column;
  transition: var(--transition-all);
  cursor: default;
}

.feature-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
  border-color: var(--color-primary-light);
}

.card-icon {
  width: 52px;
  height: 52px;
  border-radius: var(--radius-lg);
  background: var(--color-primary-light);
  color: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-5);
  transition: var(--transition-all);
}

.feature-card:hover .card-icon {
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
}

.card-title {
  font-size: var(--text-xl);
  font-weight: var(--font-bold);
  color: var(--color-text);
  margin: 0 0 var(--space-3);
}

.card-desc {
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin: 0;
  flex: 1;
}

/* ── 卡片操作按钮 ── */
.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-5);
}

.action-btn {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-full);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: var(--transition-all);
}

.action-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-light);
}

.heart-btn:active {
  transform: scale(0.85);
}

/* ── 响应式 ── */
@media (max-width: 1024px) {
  .feature-grid {
    grid-template-columns: repeat(2, 1fr);
    max-width: 680px;
  }
}

@media (max-width: 768px) {
  .feature-section {
    padding: var(--space-10) var(--space-5);
    min-height: auto;
  }
  .section-title {
    font-size: var(--text-3xl);
  }
  .section-subtitle {
    font-size: var(--text-base);
  }
  .feature-grid {
    grid-template-columns: 1fr;
    max-width: 420px;
  }
}

@media (max-width: 375px) {
  .feature-card {
    padding: var(--space-5) var(--space-4);
  }
  .section-title {
    font-size: var(--text-2xl);
  }
}

/* 无障碍 */
@media (prefers-reduced-motion: reduce) {
  .feature-card:hover {
    transform: none;
  }
}
</style>
