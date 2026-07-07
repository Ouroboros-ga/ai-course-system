<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { Users, BookOpen, Award, TrendingUp } from 'lucide-vue-next'

const sectionRef = ref(null)
const isTitleVisible = ref(false)
const isItemVisible = ref([false, false, false, false])

const stats = [
  { icon: Users, num: '10万+', label: '活跃用户', desc: '覆盖全国高校师生群体' },
  { icon: BookOpen, num: '5,000+', label: '智能课程', desc: '已生成结构化课件资源' },
  { icon: Award, num: '98%', label: '用户满意度', desc: '师生反馈好评如潮' },
  { icon: TrendingUp, num: '300%', label: '效率提升', desc: '备课与学习效率显著增长' },
]

let timeoutIds = []

const resetAnimation = () => {
  isTitleVisible.value = false
  isItemVisible.value = [false, false, false, false]
  timeoutIds.forEach(id => clearTimeout(id))
  timeoutIds = []
}

const playAnimation = () => {
  resetAnimation()
  nextTick(() => {
    const titleTimeout = setTimeout(() => {
      isTitleVisible.value = true
    }, 150)
    timeoutIds.push(titleTimeout)

    stats.forEach((_, idx) => {
      const itemTimeout = setTimeout(() => {
        isItemVisible.value[idx] = true
      }, 450 + idx * 220)
      timeoutIds.push(itemTimeout)
    })
  })
}

onMounted(() => {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        playAnimation()
      } else {
        resetAnimation()
      }
    })
  }, { threshold: 0.2 })

  if (sectionRef.value) observer.observe(sectionRef.value)
  onUnmounted(() => observer && observer.disconnect())
})
</script>

<template>
  <section class="slide value-section" ref="sectionRef">
    <div class="container-narrow">
      <h2
        class="section-title"
        :class="{ 'section-title-visible': isTitleVisible }"
      >
        赋能智慧教育 · 升级课堂体验
      </h2>

      <div class="value-grid">
        <div
          v-for="(item, index) in stats"
          :key="index"
          class="v-item"
          :class="{ 'v-item-visible': isItemVisible[index] }"
        >
          <div class="v-icon">
            <component :is="item.icon" :size="28" />
          </div>
          <span class="v-num">{{ item.num }}</span>
          <h4 class="v-label">{{ item.label }}</h4>
          <p class="v-desc">{{ item.desc }}</p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.slide {
  width: 100%;
  height: calc(100vh - var(--navbar-height));
  scroll-snap-align: start;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-12) var(--space-12) 0;
}

.value-section {
  background: var(--color-surface);
}

.container-narrow {
  max-width: 1200px;
  width: 100%;
  text-align: center;
}

.section-title {
  font-size: var(--text-4xl);
  color: var(--color-text);
  margin-bottom: var(--space-12);
  font-weight: var(--font-extrabold);
  line-height: var(--leading-tight);
  opacity: 0;
  transform: translateY(40px);
  transition: all var(--duration-slow) var(--ease);
}

.section-title-visible {
  opacity: 1;
  transform: translateY(0);
}

.value-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-6);
}

.v-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: var(--space-7) var(--space-5);
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  opacity: 0;
  transform: translateY(40px);
  transition: all var(--duration-slow) var(--ease);
}

.v-item-visible {
  opacity: 1;
  transform: translateY(0);
}

.v-item:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
  border-color: var(--color-primary-light);
}

.v-icon {
  width: 56px;
  height: 56px;
  border-radius: var(--radius-lg);
  background: var(--color-primary-light);
  color: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-5);
  transition: var(--transition-all);
}

.v-item:hover .v-icon {
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
}

.v-num {
  font-size: var(--text-3xl);
  font-weight: var(--font-extrabold);
  background: var(--gradient-primary);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  line-height: var(--leading-tight);
  margin-bottom: var(--space-2);
}

.v-label {
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--color-text);
  margin: 0 0 var(--space-2);
}

.v-desc {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin: 0;
}

/* ── 响应式 ── */
@media (max-width: 1024px) {
  .value-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .section-title {
    font-size: var(--text-3xl);
  }
}

@media (max-width: 768px) {
  .slide {
    padding: var(--space-10) var(--space-5) 0;
    height: auto;
    min-height: calc(100vh - var(--navbar-height));
  }
  .section-title {
    font-size: var(--text-2xl);
    margin-bottom: var(--space-8);
  }
  .value-grid {
    grid-template-columns: 1fr;
    gap: var(--space-4);
  }
  .v-item {
    padding: var(--space-5) var(--space-4);
  }
}

@media (max-width: 375px) {
  .section-title {
    font-size: var(--text-xl);
  }
}

/* 无障碍 */
@media (prefers-reduced-motion: reduce) {
  .section-title,
  .v-item {
    opacity: 1;
    transform: none;
    transition: none;
  }
  .v-item:hover {
    transform: none;
  }
}
</style>
