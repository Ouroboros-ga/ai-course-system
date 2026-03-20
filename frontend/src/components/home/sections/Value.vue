<template>
  <section class="slide bg-white" ref="sectionRef">
    <div class="container-narrow">
      <h2
        class="section-title"
        :class="{ 'section-title-visible': isTitleVisible }"
      >
        赋能智慧教育・升级课堂体验
      </h2>
      <div class="value-grid">
        <div
          v-for="(item, index) in items"
          :key="index"
          class="v-item"
          :class="{ 'v-item-visible': isItemVisible[index] }"
        >
          <span class="v-num">{{ item.num }}</span>
          <h4>{{ item.title }}</h4>
          <p>{{ item.desc }}</p>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'

const sectionRef = ref(null)
const isTitleVisible = ref(false)
const isItemVisible = ref([false, false, false, false])

const items = [
  { num: '01', title: '高校教学', desc: '定制化适配课程，辅助老师打造高水平课堂。' },
  { num: '02', title: '线上学习', desc: '打破时空限制，学生随时随地获得指导。' },
  { num: '03', title: '教师备课', desc: '解放生产力，让老师更聚焦于教学设计。' },
  { num: '04', title: '效率提升', desc: '无广告无水印，轻量化交互体验。' }
]

let timeoutIds = []

// 重置动画
const resetAnimation = () => {
  isTitleVisible.value = false
  isItemVisible.value = [false, false, false, false]
  timeoutIds.forEach(id => clearTimeout(id))
  timeoutIds = []
}

// 播放动画
const playAnimation = () => {
  resetAnimation()
  nextTick(() => {
    const titleTimeout = setTimeout(() => {
      isTitleVisible.value = true
    }, 150)
    timeoutIds.push(titleTimeout)

    items.forEach((_, idx) => {
      const itemTimeout = setTimeout(() => {
        isItemVisible.value[idx] = true
      }, 450 + idx * 220)
      timeoutIds.push(itemTimeout)
    })
  })
}

// 🔥 固定逻辑：只在【从上往下】进入时播放
onMounted(() => {
  let observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        // 进入视口 → 播放
        playAnimation()
      } else {
        // 离开 → 重置（方便下次回来再播）
        resetAnimation()
      }
    })
  }, { threshold: 0.2 })

  if (sectionRef.value) observer.observe(sectionRef.value)
  onUnmounted(() => observer && observer.disconnect())
})
</script>

<style scoped>
.slide {
  width: 100%;
  height: 100vh;
  scroll-snap-align: start;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 12vh 10% 0;
}
.bg-white { background: #fff; }
.container-narrow {
  max-width: 1200px;
  width: 100%;
  text-align: center;
}

.section-title {
  font-size: 3rem;
  color: #0f172a;
  margin-bottom: 5rem;
  font-weight: 700;
  opacity: 0;
  transform: translateY(60px);
  transition: all 1.1s cubic-bezier(0.25, 1, 0.5, 1);
}
.section-title-visible {
  opacity: 1;
  transform: translateY(0);
}

.value-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 3rem;
}

.v-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  text-align: left;
  padding: 3rem;
  border-bottom: 1px solid #e2e8f0;
  opacity: 0;
  transform: translateY(80px);
  transition: all 0.9s cubic-bezier(0.25, 1, 0.5, 1);
}
.v-item-visible {
  opacity: 1;
  transform: translateY(0);
}

.v-num {
  font-size: 1.1rem;
  font-weight: 800;
  color: #3b82f6;
  margin-bottom: 0.8rem;
}
.v-item h4 {
  font-size: 1.6rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 1rem;
}
.v-item p {
  font-size: 1.15rem;
  color: #475569;
  line-height: 1.7;
  margin: 0;
}
</style>
