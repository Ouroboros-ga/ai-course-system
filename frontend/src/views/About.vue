<script setup>
import AboutHero from '@/components/about/AboutHero.vue'
import AboutIntro from '@/components/about/AboutIntro.vue'
import AboutFeatures from '@/components/about/AboutFeatures.vue'
import AboutTechStack from '@/components/about/AboutTechStack.vue'
import AboutFooter from '@/components/about/AboutFooter.vue'
</script>

<template>
  <div class="about-page">
    <AboutHero class="fade-in-up" />
    <AboutIntro class="fade-in-up" />
    <AboutFeatures class="fade-in-up" />
    <AboutTechStack class="fade-in-up" />
    <AboutFooter class="fade-in-up" />
  </div>
</template>

<style scoped>
.about-page {
  width: 100%;
  min-height: 100vh;
  background: #f8fafc;
  font-family: 'Segoe UI', Roboto, sans-serif;
  padding: 40px 24px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 30px;
}

/* 高级淡入上滑动画 */
.fade-in-up {
  opacity: 0;
  transform: translateY(30px);
  animation: fadeInUp 0.8s cubic-bezier(0.22, 1, 0.36, 1) forwards;
}

/* 依次延迟，让页面一块块出现 */
.fade-in-up:nth-child(1) { animation-delay: 0.1s; }
.fade-in-up:nth-child(2) { animation-delay: 0.2s; }
.fade-in-up:nth-child(3) { animation-delay: 0.3s; }
.fade-in-up:nth-child(4) { animation-delay: 0.4s; }
.fade-in-up:nth-child(5) { animation-delay: 0.5s; }

@keyframes fadeInUp {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
