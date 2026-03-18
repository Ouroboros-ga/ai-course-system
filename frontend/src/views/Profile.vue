<script setup>
import UserIndex from "@/components/profile/UserIndex.vue";
</script>

<template>
  <div class="profile-page">
    <UserIndex />
  </div>
</template>

<style scoped>
.profile-page {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: calc(100vh - 120px);  /* 确保有足够高度 */
}
</style>
