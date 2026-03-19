<script setup>
import Hero from '@/components/home/sections/Hero.vue'
import Feature from '@/components/home/sections/Feature.vue'
import Chat from '@/components/home/sections/Chat.vue'
import Value from '@/components/home/sections/Value.vue'
import Footer from '@/components/home/sections/Footer.vue'

import ScrollArrow from '@/components/home/ui/ScrollArrow.vue'
import BackTop from '@/components/home/ui/BackTop.vue'

import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const containerRef = ref(null)

const goNext = () => {
  const container = containerRef.value
  const nextTop = container.scrollTop + window.innerHeight
  container.scrollTo({ top: nextTop, behavior: 'smooth' })
}

const goToTop = () => {
  containerRef.value.scrollTo({ top: 0, behavior: 'smooth' })
}

const goToChat = () => {
  router.push('/chat')
}
</script>

<template>
  <div class="home-wrapper">
    <div class="main-container" ref="containerRef">
      <Hero @go-chat="goToChat" />
      <Feature />
      <Chat />
      <Value />
      <Footer @go-chat="goToChat" />
    </div>

    <ScrollArrow @go-next="goNext" />
    <BackTop @go-top="goToTop" />
  </div>
</template>

<style scoped>
  /* 给每个 section 统一加顶部内边距 */
.main-container > * {
  padding-top: 70px; /* 匹配导航栏高度 */
  min-height: 100vh;
  scroll-snap-align: start;
}
.home-wrapper {
  position: fixed;
  inset: 0;
  overflow: hidden;
  background: #f8fafc;
  font-family: sans-serif;
}
.main-container {
  width: 100%;
  height: 100%;
  overflow-y: auto;
  scroll-behavior: smooth;
  scroll-snap-type: y mandatory;
  scrollbar-width: none;
}
.main-container::-webkit-scrollbar {
  display: none;
}
  /* 手机端适配（≤768px） */
  @media (max-width: 768px) {
    /* 1. 取消全屏滚动吸附，改成正常滚动 */
    .main-container {
      scroll-snap-type: none;
    }

    /* 2. 所有区块取消强制 100vh 高度，随内容自适应 */
    .main-container > * {
      min-height: auto;
      padding: 80px 20px 40px; /* 上下左右留白更舒服 */
    }

    /* 3. 第二张 Feature 卡片：3列 → 1列 */
    .feature-grid {
      grid-template-columns: 1fr !important;
      gap: 20px;
    }

    /* 4. 第三张 Chat 模块：左右布局 → 上下布局 */
    .chat-section {
      flex-direction: column !important;
      gap: 30px;
    }
    .chat-preview {
      width: 100% !important;
    }
    .chat-text {
      width: 100% !important;
      text-align: left;
    }
  }
</style>
