<script setup>
import UserIndex from "@/components/profile/UserIndex.vue";
</script>

<template>
  <div class="profile-page">
    <UserIndex class="fade-in-up" />
  </div>
</template>

<style scoped>
.profile-page {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: calc(100vh - 120px);
}

/* 🔥 项目统一高级淡入动画 */
.fade-in-up {
  opacity: 0;
  transform: translateY(35px);
  animation: fadeInUp 0.7s cubic-bezier(0.24, 1, 0.32, 1) forwards;
  animation-delay: 0.1s;
}

@keyframes fadeInUp {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
