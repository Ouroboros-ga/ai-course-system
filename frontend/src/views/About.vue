<script setup>
import AboutHero from '@/components/about/hero/AboutHero.vue'
import AboutIntro from '@/components/about/intro/AboutIntro.vue'
import AboutFeatures from '@/components/about/features/AboutFeatures.vue'
import AboutTechStack from '@/components/about/techstack/AboutTechStack.vue'
import AboutFooter from '@/components/about/footer/AboutFooter.vue'
</script>

<template>
  <div class="about-page">
    <AboutHero />
    <AboutIntro />
    <AboutFeatures />
    <AboutTechStack />
    <AboutFooter />
  </div>
</template>

<style scoped>
.about-page {
  width: 100%;
  height: 100vh;
  background: #f8fafc;
  font-family: 'Segoe UI', Roboto, sans-serif;
  padding: 40px 24px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  align-items: center;
  overflow: hidden;
}
</style>
