<!-- Profile.vue -->
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
  min-height: calc(100vh - 120px);
  /* 统一页面背景风格 */
  //background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
}
</style>
