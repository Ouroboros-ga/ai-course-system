<script setup>
import Hero from '@/components/home/sections/Hero.vue'
import Feature from '@/components/home/sections/Feature.vue'
import Chat from '@/components/home/sections/Chat.vue'
import Value from '@/components/home/sections/Value.vue'
import Footer from '@/components/home/sections/Footer.vue'

import ScrollArrow from '@/components/home/ui/ScrollArrow.vue'
import BackTop from '@/components/home/ui/BackTop.vue'

import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const containerRef = ref(null)
const showScrollArrow = ref(true)

// 监听滚动，判断是否在最后一页
const handleScroll = () => {
  const container = containerRef.value
  if (!container) return
  const maxScroll = container.scrollHeight - window.innerHeight
  const isLastPage = container.scrollTop >= maxScroll - 100
  showScrollArrow.value = !isLastPage
}

onMounted(() => {
  const container = containerRef.value
  container.addEventListener('scroll', handleScroll)
  handleScroll()
})

onUnmounted(() => {
  const container = containerRef.value
  if (container) {
    container.removeEventListener('scroll', handleScroll)
  }
})

const goNext = () => {
  const container = containerRef.value
  const nextTop = container.scrollTop + window.innerHeight
  container.scrollTo({ top: nextTop, behavior: 'smooth' })
}

const goToTop = () => {
  containerRef.value.scrollTo({ top: 0, behavior: 'smooth' })
}

const goToChat = () => {
  router.push('/profile')
}
</script>

<template>
  <div class="home-wrapper">
    <div class="main-container" ref="containerRef">
      <Hero @go-chat="goToChat" />
      <Feature />
      <Chat @go-chat="goToChat" />
      <Value />
      <Footer @go-chat="goToChat" />
    </div>

    <!-- 正常显示，最后一页自动隐藏 -->
    <ScrollArrow v-if="showScrollArrow" @go-next="goNext" />
    <BackTop @go-top="goToTop" />
  </div>
</template>

<style scoped>
.home-wrapper {
  position: fixed;
  top: var(--navbar-height);
  left: 0;
  right: 0;
  bottom: 0;
  overflow: hidden;
  background: var(--color-bg);
  font-family: var(--font-sans);
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

/* 给每个 section 统一加顶部内边距 */
.main-container > * {
  padding-top: var(--space-10);
  min-height: calc(100vh - var(--navbar-height));
  scroll-snap-align: start;
}

/* 手机端适配（≤768px） */
@media (max-width: 768px) {
  .main-container {
    scroll-snap-type: none;
  }
  .main-container > * {
    min-height: auto;
    padding: var(--space-10) var(--space-5) var(--space-8);
  }
}
</style>
