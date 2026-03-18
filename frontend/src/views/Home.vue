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
</style>
