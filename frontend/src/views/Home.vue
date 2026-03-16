<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const current = ref(0)
const isScrolling = ref(false)

onMounted(() => {
  const slides = document.querySelectorAll('.slide')

  const handleWheel = (e) => {
    if (isScrolling.value) return
    if (Math.abs(e.deltaY) < 50) return

    isScrolling.value = true

    if (e.deltaY > 0) {
      if (current.value < slides.length - 1) current.value++
    } else {
      if (current.value > 0) current.value--
    }

    slides[current.value].scrollIntoView({
      behavior: 'smooth',
      block: 'start'
    })

    setTimeout(() => {
      isScrolling.value = false
    }, 500)
  }

  window.addEventListener('wheel', handleWheel)
  onUnmounted(() => {
    window.removeEventListener('wheel', handleWheel)
  })
})

// 点击箭头下一页
const goNext = () => {
  const slides = document.querySelectorAll('.slide')
  if (isScrolling.value) return
  if (current.value >= slides.length - 1) return

  isScrolling.value = true
  current.value++
  slides[current.value].scrollIntoView({ behavior: 'smooth', block: 'start' })
  setTimeout(() => { isScrolling.value = false }, 500)
}

// 点击立即使用 → 跳转到聊天页面
const goToChat = () => {
  router.push('/chat')
}

// 🔥 回到顶部（回到第一页）
const goToTop = () => {
  if (isScrolling.value) return
  current.value = 0
  const slides = document.querySelectorAll('.slide')
  slides[0].scrollIntoView({ behavior: 'smooth', block: 'start' })
  setTimeout(() => { isScrolling.value = false }, 500)
}
</script>

<template>
  <div>
    <div class="container">
      <div class="slide page1">
        <div class="hero-content">
          <h1 class="main-title">泛雅 AI 智课 实时互动<br>免费试用 - 重构课堂体验</h1>
          <p class="sub-title">
            基于泛雅平台的 AI 互动智课生成与实时问答系统！融合 RAG 与大模型技术，自动生成互动课件、智能续接学习进度、7×24 小时实时答疑。免费无水印，支持高校教学场景，助力教育数字化升级，让每一堂课都更智能、更高效！
          </p>

          <button class="use-btn" @click="goToChat">立即使用</button>
        </div>
      </div>

      <div class="slide page2"></div>
      <div class="slide page3"></div>
      <div class="slide page4"></div>
    </div>

    <div class="scroll-arrow" @click="goNext">↓</div>

    <!-- 🔥 右下角回到顶部按钮（你要的位置） -->
    <button class="back-top" @click="goToTop">↑</button>
  </div>
</template>

<style scoped>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  margin: 0;
  padding: 0;
  overflow: hidden;
}

.container {
  width: 100%;
  height: 100vh;
  overflow: hidden;
}

.slide {
  width: 100%;
  height: 100vh;
  background-size: cover;
  background-position: center;
  position: relative;
}

.page1 {
  background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
}

.page2 { background-image: url('@/assets/home/主页照片1.png'); }
.page3 { background-image: url('@/assets/home/主页照片1.png'); }
.page4 { background-image: url('@/assets/home/主页照片1.png'); }

.hero-content {
  position: absolute;
  top: 42%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  width: 90%;
  max-width: 1200px;
  color: #0f172a;
}

.main-title {
  font-size: clamp(2.5rem, 6vw, 4.5rem);
  font-weight: 700;
  line-height: 1.1;
  margin-bottom: 1.8rem;
}

.sub-title {
  font-size: clamp(1rem, 2vw, 1.25rem);
  line-height: 1.7;
  color: #334155;
  max-width: 900px;
  margin: 0 auto 2.5rem;
}

.use-btn {
  padding: 16px 48px;
  font-size: 18px;
  font-weight: 600;
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
  color: white;
  border: none;
  border-radius: 50px;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 8px 20px rgba(59, 130, 246, 0.3);
}

.use-btn:hover {
  transform: translateY(-3px);
  box-shadow: 0 12px 24px rgba(59, 130, 246, 0.4);
}

.scroll-arrow {
  position: fixed;
  bottom: 35px;
  left: 50%;
  transform: translateX(-50%);
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background-color: rgba(100, 100, 100, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  color: #fff;
  z-index: 999;
  cursor: pointer;
}

/* 🔥 右下角回到顶部按钮样式 */
.back-top {
  position: fixed;
  right: 30px;
  bottom: 30px;
  width: 50px;
  height: 50px;
  border-radius: 50%;
  background: rgba(59, 130, 246, 0.9);
  color: white;
  font-size: 22px;
  border: none;
  cursor: pointer;
  z-index: 999;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

.back-top:hover {
  background: #1d4ed8;
  transform: scale(1.08);
}
</style>
