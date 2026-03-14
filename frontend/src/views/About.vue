<template>
  <div class="about-page">
    <AboutContent />
  </div>
</template>

<script setup>
import AboutContent from '../components/about/AboutContent.vue'
</script>

<style scoped>
.about-page {
  height: 75vh;
  display: flex;
  flex-direction: column;
  background-color: rgba(0, 0, 0, 0);
  padding-bottom: env(safe-area-inset-bottom, 80);
}
</style>
