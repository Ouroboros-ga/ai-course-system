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
  min-height: 100vh;
}

.fade-in-up {
  min-height: inherit;
}
</style>
